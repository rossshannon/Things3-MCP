"""Build, sign and install one explicitly configured macOS bridge application."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNIX_PATH_LIMIT = 104


class PackagingError(RuntimeError):
    """A build or lifecycle gate did not pass."""


@dataclass(frozen=True)
class BuildConfig:
    """The single app identity and relative-path contract used by every script."""

    name: str
    bundle_id: str
    entrypoint: str
    icon: str | None
    usage_description: str
    state_directory: str
    socket_name: str
    token_name: str
    collect_submodules: tuple[str, ...] = ()
    environment_patterns: dict[str, str] = field(default_factory=dict)
    sandbox_read_only_home: tuple[str, ...] = ()
    apple_event_targets: tuple[str, ...] = ()
    state_environment: dict[str, str] = field(default_factory=dict)
    local_signing_identity: str = ""

    def __post_init__(self) -> None:
        """Reject invalid names, paths and declared capabilities."""
        if not self.name or any(char in self.name for char in "/\\\n\r\0") or self.name in {".", ".."}:
            raise PackagingError("App name must be a single filename without control characters")
        if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", self.bundle_id):
            raise PackagingError("Invalid bundle identifier")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:main", self.entrypoint):
            raise PackagingError("Entrypoint must be a fixed module:main")
        for value in (self.state_directory, self.socket_name, self.token_name, *self.sandbox_read_only_home, *self.state_environment.values(), *((self.icon,) if self.icon else ())):
            path = Path(value)
            if not value or value == "." or path.is_absolute() or ".." in path.parts or any(char in value for char in "\0\n\r"):
                raise PackagingError("Runtime paths must be relative to the user's home without traversal")
        if Path(self.socket_name).name != self.socket_name or Path(self.token_name).name != self.token_name:
            raise PackagingError("Socket and token names must be single filenames")
        for module in self.collect_submodules:
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module):
                raise PackagingError("Invalid collected module name")
        for target in self.apple_event_targets:
            if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", target):
                raise PackagingError("Invalid Apple Events target")
        if self.apple_event_targets and not self.usage_description.strip():
            raise PackagingError("Apple Events targets require a usage description")
        for name in (*self.environment_patterns, *self.state_environment):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                raise PackagingError("Invalid environment variable name")
        for pattern in self.environment_patterns.values():
            re.compile(pattern)


def load_config(path: Path) -> BuildConfig:
    """Reject misspelled or missing configuration fields before doing any work."""
    raw = tomllib.loads(path.read_text())
    for key in ("collect_submodules", "sandbox_read_only_home", "apple_event_targets"):
        if key in raw:
            if not isinstance(raw[key], list) or not all(isinstance(value, str) for value in raw[key]):
                raise PackagingError(f"{key} must be a list of strings")
            raw[key] = tuple(raw[key])
    raw.setdefault("icon", None)
    try:
        return BuildConfig(**raw)
    except (TypeError, ValueError) as error:
        raise PackagingError(f"Invalid build configuration: {error}") from error


def run_command(argv: list[str], *, check: bool = True, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a fixed argument vector without a shell."""
    return subprocess.run(argv, check=check, text=True, capture_output=True, **kwargs)


def info_plist(config: BuildConfig, version: str) -> dict[str, Any]:
    """Render bundle metadata from the package version and app configuration."""
    data: dict[str, Any] = {
        "CFBundleExecutable": config.name,
        "CFBundleIdentifier": config.bundle_id,
        "CFBundleName": config.name,
        "CFBundleDisplayName": config.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSUIElement": True,
    }
    if config.icon:
        data["CFBundleIconFile"] = Path(config.icon).name
    if config.usage_description:
        data["NSAppleEventsUsageDescription"] = config.usage_description
    return data


def entitlements(config: BuildConfig, sandbox: bool) -> dict[str, Any]:
    """Return only the app's declared capabilities, without network permissions."""
    data: dict[str, Any] = {}
    if config.apple_event_targets:
        data["com.apple.security.automation.apple-events"] = True
    if sandbox:
        data["com.apple.security.app-sandbox"] = True
        if config.sandbox_read_only_home:
            data["com.apple.security.temporary-exception.files.home-relative-path.read-only"] = [f"/{path.rstrip('/')}/" for path in config.sandbox_read_only_home]
        if config.apple_event_targets:
            data["com.apple.security.temporary-exception.apple-events"] = list(config.apple_event_targets)
    return data


def digest(path: Path) -> str:
    """Hash an input or artifact without loading a large binary into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact_files(app: Path) -> dict[str, str]:
    """Record files and symlink destinations in the sealed app."""
    result = {}
    for path in sorted(app.rglob("*")):
        key = str(path.relative_to(app))
        if path.is_symlink():
            result[key] = f"symlink:{os.readlink(path)}"
        elif path.is_file():
            result[key] = digest(path)
    return result


def source_inputs(root: Path) -> dict[str, str]:
    """Attribute dirty source builds and detect inputs changing during a build."""
    paths = [root / name for name in ("pyproject.toml", "uv.lock", ".python-version")]
    paths.extend(sorted((root / "src").rglob("*.py")))
    return {str(path.relative_to(root)): digest(path) for path in paths}


def build(config: BuildConfig, config_path: Path, root: Path, output: Path, sandbox: bool) -> Path:
    """Build onedir from a dedicated, exactly synchronised locked environment."""
    if sys.platform != "darwin":
        raise PackagingError("macOS app builds require macOS")
    architecture = platform.machine()
    if architecture not in {"arm64", "x86_64"}:
        raise PackagingError("Build on a native arm64 or x86_64 interpreter")
    project = tomllib.loads((root / "pyproject.toml").read_text())
    version = project["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise PackagingError("The bundle requires a three-part numeric release version")
    target = output / f"{config.name}.app"
    if target.exists() or target.is_symlink():
        raise PackagingError(f"Output already exists; choose a fresh --output directory: {target}")
    inputs = source_inputs(root)
    lock_digest = digest(root / "uv.lock")
    icon = root / config.icon if config.icon else None
    if icon and not icon.is_file():
        raise PackagingError("Configured icon is missing")
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="bridge-build-", dir=output))
    build_env = work / "venv"
    environment = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(build_env), PYTHONHASHSEED="0")
    pin = (root / ".python-version").read_text().strip()
    run_command(["uv", "sync", "--locked", "--no-default-groups", "--group", "build", "--python", pin], cwd=root, env=environment)
    python = build_env / "bin/python"
    tool_probe = (
        "import importlib.metadata,json,os,platform,sys; "
        "print(json.dumps({'python':sys.version,'python_executable':sys.executable,"
        "'python_resolved_executable':os.path.realpath(sys.executable),"
        "'architecture':platform.machine(),'pyinstaller':importlib.metadata.version('pyinstaller'),"
        "'hooks':importlib.metadata.version('pyinstaller-hooks-contrib')}))"
    )
    tool_data = json.loads(run_command([str(python), "-c", tool_probe]).stdout)
    if tool_data["architecture"] != architecture:
        raise PackagingError("Build interpreter architecture differs from the host interpreter")
    module = config.entrypoint.split(":")[0]
    entrypoint = work / "bridge_entry.py"
    entrypoint.write_text(f"from {module} import main\n\nif __name__ == '__main__':\n    raise SystemExit(main())\n")
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        config.name,
        "--osx-bundle-identifier",
        config.bundle_id,
        "--target-architecture",
        architecture,
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work),
        "--paths",
        str(root / "src"),
    ]
    if icon:
        command += ["--icon", str(icon)]
    for module in config.collect_submodules:
        command += ["--collect-submodules", module]
    run_command([*command, str(entrypoint)], cwd=root, env=environment)
    app = work / "dist" / f"{config.name}.app"
    resources = app / "Contents/Resources"
    with (app / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump(info_plist(config, version), stream)
    if icon:
        shutil.copy2(icon, resources / icon.name)
    revision = run_command(["git", "-C", str(root), "rev-parse", "HEAD"], check=False)
    dirty = run_command(["git", "-C", str(root), "status", "--porcelain"], check=False)
    sdk = run_command(["xcrun", "--show-sdk-version"], check=False)
    manifest = {
        "bundle_id": config.bundle_id,
        "version": version,
        "build_id": uuid.uuid4().hex,
        "source_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "lock_sha256": lock_digest,
        "config_sha256": digest(config_path),
        "entrypoint": config.entrypoint,
        "tools": {**tool_data, "uv": run_command(["uv", "--version"]).stdout.strip()},
        "host": {"os": platform.platform(), "sdk": sdk.stdout.strip(), "architecture": architecture},
        "sandbox": sandbox,
        "entitlements": entitlements(config, sandbox),
        "source_inputs_sha256": inputs,
    }
    if source_inputs(root) != inputs:
        raise PackagingError("Source inputs changed during the build; retry after source changes finish")
    (resources / "build-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    # All metadata is final before the separate signing command seals the app.
    if target.exists():
        raise PackagingError(f"Output already exists; choose a fresh --output directory: {target}")
    os.replace(app, target)
    (output / f"{config.name}.unsigned-files.json").write_text(json.dumps(artifact_files(target), indent=2, sort_keys=True) + "\n")
    return target


def bundle_manifest(app: Path, config: BuildConfig) -> dict[str, Any]:
    """Require the app metadata, configuration and recorded identity to agree."""
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    manifest = json.loads((app / "Contents/Resources/build-manifest.json").read_text())
    if info.get("CFBundleIdentifier") != config.bundle_id or info.get("CFBundleExecutable") != config.name:
        raise PackagingError("Bundle identity does not match the selected configuration")
    if manifest.get("bundle_id") != config.bundle_id or manifest.get("version") != info.get("CFBundleShortVersionString") or not manifest.get("build_id"):
        raise PackagingError("Build manifest and bundle identity disagree")
    return manifest


def verify_bundle(app: Path, config: BuildConfig) -> dict[str, Any]:
    """Verify integrity before reading metadata as installation evidence."""
    run_command(["codesign", "--verify", "--deep", "--strict", str(app)])
    signature = run_command(["codesign", "-dv", "--verbose=4", str(app)])
    if f"Identifier={config.bundle_id}" not in (signature.stdout + signature.stderr).splitlines():
        raise PackagingError("Signed identifier does not match the selected configuration")
    return bundle_manifest(app, config)


def signing_targets(app: Path) -> list[Path]:
    """Find nested Mach-O files and bundle containers in inside-out order."""
    magic = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}
    targets = []
    for path in app.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            with path.open("rb") as stream:
                if stream.read(4) in magic:
                    targets.append(path)
        elif path.suffix in {".app", ".framework", ".xpc", ".bundle"}:
            targets.append(path)
    return sorted(targets, key=lambda item: (-len(item.parts), str(item)))


def sign(config: BuildConfig, app: Path, profile: str, identity: str | None) -> Path:
    """Sign using an existing identity; never create keys or change trust."""
    manifest = bundle_manifest(app, config)
    if profile == "ad-hoc-test":
        if identity:
            raise PackagingError("The ad-hoc-test profile does not accept a signing identity")
        identity = "-"
        print("Ad-hoc test signing does not provide a persistent TCC identity.", file=sys.stderr)
    else:
        if profile == "local" and not identity:
            identity = config.local_signing_identity
        if not identity or identity == "-":
            raise PackagingError("This signing profile requires an existing --identity")
        identities = run_command(["security", "find-identity", "-v", "-p", "codesigning"]).stdout
        available = re.findall(r'[0-9]+\)\s+([A-Fa-f0-9]{40})\s+"([^"]+)"', identities)
        match = next(((fingerprint, name) for fingerprint, name in available if identity in {fingerprint, name}), None)
        if match is None:
            raise PackagingError("Signing identity is unavailable; no certificate or trust settings were changed")
        if profile == "developer-id" and not match[1].startswith("Developer ID Application:"):
            raise PackagingError("The developer-id profile requires a Developer ID Application identity")
        if profile == "local" and match[1].startswith("Developer ID Application:"):
            raise PackagingError("Use the developer-id profile for a Developer ID Application identity")
        identity = match[0]
    sandbox = bool(manifest.get("sandbox"))
    expected_entitlements = entitlements(config, sandbox)
    if manifest.get("entitlements") != expected_entitlements:
        raise PackagingError("Build entitlements do not match the selected configuration")
    with tempfile.TemporaryDirectory(prefix="bridge-sign-") as directory:
        entitlement_path = Path(directory) / "main.plist"
        entitlement_path.write_bytes(plistlib.dumps(expected_entitlements))
        base = ["codesign", "--force", "--sign", identity]
        base += ["--options", "runtime", "--timestamp"] if profile == "developer-id" else ["--timestamp=none"]
        main_executable = app / "Contents/MacOS" / config.name
        for target in signing_targets(app):
            args = [*base]
            if target == main_executable:
                args += ["--entitlements", str(entitlement_path)]
            run_command([*args, str(target)])
        run_command([*base, "--entitlements", str(entitlement_path), str(app)])
    verify_bundle(app, config)
    description = run_command(["codesign", "-d", "--requirements", "-", "--entitlements", ":-", "--verbose=4", str(app)])
    proof = app.parent / f"{app.stem}.signed-artifact.json"
    proof.write_text(json.dumps({"build_id": manifest["build_id"], "profile": profile, "signature": description.stdout + description.stderr, "files": artifact_files(app)}, indent=2, sort_keys=True) + "\n")
    return proof


def runtime_paths(config: BuildConfig, home: Path, sandbox: bool) -> tuple[Path, Path, Path]:
    """Keep legacy defaults unless the candidate explicitly enables sandboxing."""
    state = home / "Library/Containers" / config.bundle_id / "Data" if sandbox else home / config.state_directory
    socket_path = state / config.socket_name
    if len(os.fsencode(socket_path)) >= UNIX_PATH_LIMIT:
        raise PackagingError("Socket pathname exceeds macOS's 103-byte limit; use a shorter HOME or app identity")
    return state, socket_path, state / config.token_name


def launchagent(config: BuildConfig, home: Path, target: Path, sandbox: bool) -> dict[str, Any]:
    """Render XML-safe launchd metadata; stdout/stderr never become unbounded files."""
    state, socket_path, token_path = runtime_paths(config, home, sandbox)
    environment = {}
    if sandbox:
        environment.update({name: str(state / relative) for name, relative in config.state_environment.items()})
    for name, pattern in config.environment_patterns.items():
        value = os.environ.get(name, "")
        if value:
            if not re.fullmatch(pattern, value):
                raise PackagingError(f"Invalid value for {name}")
            environment[name] = value
    return {
        "Label": config.bundle_id,
        "AssociatedBundleIdentifiers": [config.bundle_id],
        "ProgramArguments": [str(target / "Contents/MacOS" / config.name), "--socket", str(socket_path), "--token-file", str(token_path)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "Umask": 0o077,
        # The bridge uses structured diagnostics. Discard unsolicited process output
        # rather than persisting potentially private payloads or unbounded logs.
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "WorkingDirectory": str(state),
        "EnvironmentVariables": environment,
    }


def authenticated_status(socket_path: Path, token_path: Path) -> dict[str, Any]:
    """Read bounded authenticated status over the candidate's Unix socket."""
    reject_symlinks(token_path)
    descriptor = os.open(token_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise PackagingError("Readiness token must be an owner-only regular file")
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096:
            raise PackagingError("Invalid readiness token length")
        token = raw.decode("ascii").strip()
    finally:
        os.close(descriptor)
    if not token or len(token) > 4096 or "\n" in token or "\r" in token:
        raise PackagingError("Invalid readiness token")
    reject_symlinks(socket_path)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(1)
    try:
        connection.connect(str(socket_path))
        connection.sendall(f"GET /status HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n".encode())
        response = http.client.HTTPResponse(connection)
        response.begin()
        body = response.read(65537)
        if response.status != 200 or len(body) > 65536:
            raise PackagingError("Candidate did not return bounded authenticated status")
        envelope = json.loads(body)
        if not envelope.get("ok") or not isinstance(envelope.get("data"), dict):
            raise PackagingError("Candidate returned an invalid status envelope")
        return envelope["data"]
    finally:
        connection.close()


def service_loaded(domain: str) -> bool:
    """Inspect only this app's launchd job."""
    return run_command(["launchctl", "print", domain], check=False).returncode == 0


def wait_ready(config: BuildConfig, home: Path, target: Path, manifest: dict[str, Any], timeout: float) -> None:
    """Match authenticated build metadata to both launchd's PID and executable."""
    _, socket_path, token_path = runtime_paths(config, home, bool(manifest.get("sandbox")))
    executable = str(target / "Contents/MacOS" / config.name)
    domain = f"gui/{os.getuid()}/{config.bundle_id}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = authenticated_status(socket_path, token_path)
            identity = status.get("identity", {})
            job = run_command(["launchctl", "print", domain])
            pid_match = re.search(r"^\s*pid = (\d+)\s*$", job.stdout, re.MULTILINE)
            pid = int(pid_match[1]) if pid_match else None
            if pid and status.get("pid") == pid and status.get("executable") == executable and status.get("instance_id"):
                process = run_command(["ps", "-p", str(pid), "-o", "comm="]).stdout.strip()
                if process == executable and all(identity.get(key) == manifest[key] for key in ("bundle_id", "version", "build_id")):
                    return
        except (OSError, ValueError, PackagingError, subprocess.CalledProcessError, http.client.HTTPException):
            pass
        if time.monotonic() >= deadline:
            raise PackagingError("Candidate readiness failed: authenticated identity, launchd PID and executable must agree")
        time.sleep(0.1)


def reject_symlinks(path: Path) -> None:
    """Reject symlinks in the supplied path and every ancestor."""
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise PackagingError(f"Refusing symlink path: {component}")


def ensure_directory(path: Path, *, private: bool = False) -> None:
    """Create missing directories; preserve modes on shared existing parents."""
    reject_symlinks(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise PackagingError(f"Directory is not owned by the current user: {path}")
    if private:
        path.chmod(0o700)


def atomic_write(path: Path, content: bytes) -> None:
    """Replace a small file from an owner-only temporary on the same volume."""
    descriptor, filename = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(config: BuildConfig, source: Path, home: Path, timeout: float = 15) -> Path:
    """Verify and stage first, then replace with recovery of the previous app/job."""
    manifest = verify_bundle(source, config)
    target = home / "Applications" / f"{config.name}.app"
    plist = home / "Library/LaunchAgents" / f"{config.bundle_id}.plist"
    reject_symlinks(target)
    reject_symlinks(plist)
    candidate_plist = plistlib.dumps(launchagent(config, home, target, bool(manifest.get("sandbox"))))
    ensure_directory(target.parent)
    ensure_directory(plist.parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{config.bundle_id}-install-", dir=target.parent))
    candidate = staging / "candidate.app"
    shutil.copytree(source, candidate, symlinks=True)
    if verify_bundle(candidate, config) != manifest:
        raise PackagingError("Candidate changed while staging; installation left untouched")
    previous_plist = plist.read_bytes() if plist.exists() else None
    if previous_plist is not None:
        atomic_write(staging / "previous.plist", previous_plist)
    previous_app = staging / "previous.app"
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{config.bundle_id}"
    was_loaded = service_loaded(service)
    if was_loaded and previous_plist is None:
        raise PackagingError("Existing job has no recoverable plist; installation left untouched")
    moved_previous = False
    installed_candidate = False
    try:
        if was_loaded:
            run_command(["launchctl", "bootout", service])
        if target.exists():
            os.replace(target, previous_app)
            moved_previous = True
        os.replace(candidate, target)
        installed_candidate = True
        atomic_write(plist, candidate_plist)
        state, _, _ = runtime_paths(config, home, bool(manifest.get("sandbox")))
        ensure_directory(state, private=True)
        run_command(["launchctl", "bootstrap", domain, str(plist)])
        wait_ready(config, home, target, manifest, timeout)
    except BaseException as error:
        try:
            if service_loaded(service):
                run_command(["launchctl", "bootout", service])
            if installed_candidate:
                os.replace(target, staging / "failed-candidate.app")
            if moved_previous:
                os.replace(previous_app, target)
            if previous_plist is None:
                plist.unlink(missing_ok=True)
            else:
                atomic_write(plist, previous_plist)
            if was_loaded:
                run_command(["launchctl", "bootstrap", domain, str(plist)])
                if not service_loaded(service):
                    raise PackagingError("Restored job is not loaded")
        except BaseException as rollback_error:
            raise PackagingError(f"Installation failed ({error}); rollback also failed ({rollback_error}). Recovery files: {staging}") from error
        raise PackagingError(f"Installation failed ({error}); previous installation restored. Recovery files: {staging}") from error
    return staging


def uninstall(config: BuildConfig, home: Path) -> None:
    """Remove only this agent and app, preserving tokens, journals and caches."""
    target = home / "Applications" / f"{config.name}.app"
    plist = home / "Library/LaunchAgents" / f"{config.bundle_id}.plist"
    reject_symlinks(target)
    reject_symlinks(plist)
    domain = f"gui/{os.getuid()}/{config.bundle_id}"
    if service_loaded(domain):
        run_command(["launchctl", "bootout", domain])
    plist.unlink(missing_ok=True)
    if target.exists():
        shutil.rmtree(target)


def main() -> int:
    """Dispatch the four documented packaging operations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "sign", "install", "uninstall"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--profile", choices=("local", "developer-id", "ad-hoc-test"), default="local")
    parser.add_argument("--identity", help="Existing Keychain identity name or SHA-1 fingerprint")
    parser.add_argument("--adhoc", action="store_true", help="Compatibility alias for --profile ad-hoc-test; no persistent TCC identity")
    parser.add_argument("--sandbox-experimental", action="store_true")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        root = args.root.resolve()
        config_path = (args.config or root / "packaging/macos/bridge.toml").resolve()
        config = load_config(config_path)
        output = (args.output or root / "build/macos").resolve()
        app = (args.app or output / f"{config.name}.app").resolve()
        if args.operation == "build":
            print(build(config, config_path, root, output, args.sandbox_experimental))
        elif args.operation == "sign":
            print(sign(config, app, "ad-hoc-test" if args.adhoc else args.profile, args.identity))
        elif args.operation == "install":
            print(f"Installed and verified candidate; previous files retained at {install(config, app, args.home.resolve(), args.timeout)}")
        else:
            uninstall(config, args.home.resolve())
            print("Removed this app and LaunchAgent; private state and installation backups were preserved.")
    except (PackagingError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Packaging failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
