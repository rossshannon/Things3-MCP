import json
import plistlib
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from clawbridge import packaging


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    home = tmp_path / "mcp-test Home & Friends"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Lifecycle tests never bind a socket. Exercise the real pathname limit
    # separately; pytest's temporary root can itself approach macOS's limit.
    monkeypatch.setattr(packaging, "UNIX_PATH_LIMIT", 4096)
    config = packaging.BuildConfig(
        name="ClawBridge Example",
        bundle_id="org.example.ClawBridgeExample",
        entrypoint="clawbridge.demo:main",
        icon=None,
        usage_description="",
        state_directory="Library/Application Support/ClawBridgeExample",
        socket_name="bridge.sock",
        token_name="token",  # noqa: S106 -- filename, not a credential
        collect_submodules=("clawbridge",),
    )
    source = tmp_path / "candidate.app"
    (source / "Contents/Resources").mkdir(parents=True)
    (source / "Contents/MacOS").mkdir()
    (source / "Contents/MacOS" / config.name).write_text("synthetic executable")
    with (source / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": config.bundle_id, "CFBundleExecutable": config.name, "CFBundleShortVersionString": "2.5.0"}, stream)
    manifest = {"bundle_id": config.bundle_id, "version": "2.5.0", "build_id": "candidate-build", "sandbox": False, "entitlements": {}}
    (source / "Contents/Resources/build-manifest.json").write_text(json.dumps(manifest))
    calls = []
    loaded = {"value": True}
    fail_bootstrap = {"value": False}

    def command(argv, **kwargs):
        calls.append(argv)
        output = ""
        code = 0
        if argv[0] == "codesign" and "-dv" in argv:
            output = f"Identifier={config.bundle_id}\n"
        elif argv[:2] == ["launchctl", "print"]:
            code = 0 if loaded["value"] else 113
            output = "pid = 4242\n"
        elif argv[:2] == ["launchctl", "bootout"]:
            loaded["value"] = False
        elif argv[:2] == ["launchctl", "bootstrap"]:
            if fail_bootstrap["value"]:
                fail_bootstrap["value"] = False
                code = 5
            else:
                loaded["value"] = True
        elif argv[0] == "ps":
            output = str(home / "Applications" / f"{config.name}.app/Contents/MacOS" / config.name)
        result = subprocess.CompletedProcess(argv, code, output, "")
        if kwargs.get("check", True) and code:
            raise subprocess.CalledProcessError(code, argv, output)
        return result

    monkeypatch.setattr(packaging, "run_command", command)
    monkeypatch.setattr(
        packaging, "authenticated_status", lambda *_: {"pid": 4242, "executable": str(home / "Applications" / f"{config.name}.app/Contents/MacOS" / config.name), "instance_id": "new-instance", "identity": manifest}
    )
    return config, source, home, calls, fail_bootstrap


def old_install(config, home):
    target = home / "Applications" / f"{config.name}.app"
    target.mkdir(parents=True)
    (target / "old-marker").write_text("old")
    plist = home / "Library/LaunchAgents" / f"{config.bundle_id}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"old-plist")
    state = home / config.state_directory
    state.mkdir(parents=True)
    (state / "token").write_text("preserve-token")
    return target, plist, state


def test_tampered_signature_is_rejected_before_stopping(fixture, monkeypatch):
    config, source, home, calls, _ = fixture
    target, plist, _ = old_install(config, home)
    original = packaging.run_command

    def reject(argv, **kwargs):
        if argv[:2] == ["codesign", "--verify"]:
            raise subprocess.CalledProcessError(1, argv)
        return original(argv, **kwargs)

    monkeypatch.setattr(packaging, "run_command", reject)
    with pytest.raises(subprocess.CalledProcessError):
        packaging.install(config, source, home, timeout=0)
    assert (target / "old-marker").exists()
    assert plist.read_bytes() == b"old-plist"
    assert not any(call[0] == "launchctl" for call in calls)


def test_bootstrap_failure_restores_app_plist_and_service(fixture):
    config, source, home, calls, fail_bootstrap = fixture
    target, plist, state = old_install(config, home)
    fail_bootstrap["value"] = True
    with pytest.raises(packaging.PackagingError, match="previous installation restored"):
        packaging.install(config, source, home, timeout=0)
    assert (target / "old-marker").read_text() == "old"
    assert plist.read_bytes() == b"old-plist"
    assert (state / "token").read_text() == "preserve-token"
    assert len([call for call in calls if call[:2] == ["launchctl", "bootstrap"]]) == 2


def test_old_listener_cannot_pass_readiness(fixture, monkeypatch):
    config, source, home, _, _ = fixture
    target, _, _ = old_install(config, home)
    monkeypatch.setattr(
        packaging, "authenticated_status", lambda *_: {"pid": 4242, "instance_id": "stale", "executable": "old", "identity": {"bundle_id": config.bundle_id, "version": "2.5.0", "build_id": "old-build"}}
    )
    with pytest.raises(packaging.PackagingError, match="previous installation restored"):
        packaging.install(config, source, home, timeout=0)
    assert (target / "old-marker").exists()


def test_home_escaping_and_uninstall_preserves_state(fixture):
    config, source, home, calls, _ = fixture
    target, plist, state = old_install(config, home)
    packaging.install(config, source, home, timeout=0)
    data = plistlib.loads(plist.read_bytes())
    assert data["ProgramArguments"][0] == str(target / "Contents/MacOS" / config.name)
    assert data["AssociatedBundleIdentifiers"] == [config.bundle_id]
    assert data["Umask"] == 0o077
    assert plist.stat().st_mode & 0o777 == 0o600
    packaging.uninstall(config, home)
    assert not target.exists()
    assert not plist.exists()
    assert (state / "token").read_text() == "preserve-token"
    assert not any("unload" in call for call in calls)


def competing_lifecycle(config, source, home, operation):
    code = """
import json
import sys
from pathlib import Path
from clawbridge import packaging

def no_system_commands(*args, **kwargs):
    raise AssertionError('Competing operation reached a system command')

packaging.run_command = no_system_commands
config = packaging.BuildConfig(**json.loads(sys.argv[1]))
try:
    if sys.argv[4] == 'install':
        packaging.install(config, Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        packaging.uninstall(config, Path(sys.argv[3]))
except packaging.PackagingError as error:
    if 'Another lifecycle operation' not in str(error):
        raise
    print('blocked')
else:
    raise AssertionError('Competing lifecycle operation was admitted')
"""
    return subprocess.run([sys.executable, "-c", code, json.dumps(asdict(config)), str(source), str(home), operation], capture_output=True, text=True, timeout=10, check=False)


@pytest.mark.parametrize("operation", ["install", "uninstall"])
@pytest.mark.parametrize("phase", ["snapshot", "readiness", "rollback"])
def test_install_holds_shared_lock_through_snapshot_readiness_and_rollback(fixture, monkeypatch, operation, phase):
    config, source, home, _, _ = fixture
    target, plist, _ = old_install(config, home)
    probes = []

    def probe():
        probes.append(competing_lifecycle(config, source, home, operation))

    if phase == "snapshot":
        read_bytes = Path.read_bytes

        def before_snapshot(path):
            if path == plist and not probes:
                probe()
            return read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", before_snapshot)
    elif phase == "readiness":
        wait_ready = packaging.wait_ready

        def during_readiness(*args):
            probe()
            return wait_ready(*args)

        monkeypatch.setattr(packaging, "wait_ready", during_readiness)
    else:
        atomic_write = packaging.atomic_write

        def during_rollback(path, content):
            if path == plist and content == b"old-plist":
                probe()
            return atomic_write(path, content)

        def fail_readiness(*args):
            raise packaging.PackagingError("synthetic readiness failure")

        monkeypatch.setattr(packaging, "atomic_write", during_rollback)
        monkeypatch.setattr(packaging, "wait_ready", fail_readiness)
    if phase == "rollback":
        with pytest.raises(packaging.PackagingError, match="previous installation restored"):
            packaging.install(config, source, home, timeout=0)
        assert (target / "old-marker").read_text() == "old"
        assert plist.read_bytes() == b"old-plist"
    else:
        packaging.install(config, source, home, timeout=0)
    assert len(probes) == 1
    assert probes[0].returncode == 0, probes[0].stderr
    assert probes[0].stdout.strip() == "blocked"
    packaging.uninstall(config, home)
    assert not target.exists()


@pytest.mark.parametrize("operation", ["install", "uninstall"])
def test_uninstall_holds_same_interprocess_lock(fixture, monkeypatch, operation):
    config, source, home, _, _ = fixture
    target, plist, _ = old_install(config, home)
    service_loaded = packaging.service_loaded
    probes = []

    def before_service_observation(domain):
        probes.append(competing_lifecycle(config, source, home, operation))
        return service_loaded(domain)

    monkeypatch.setattr(packaging, "service_loaded", before_service_observation)
    packaging.uninstall(config, home)
    assert len(probes) == 1
    assert probes[0].returncode == 0, probes[0].stderr
    assert probes[0].stdout.strip() == "blocked"
    assert not target.exists()
    assert not plist.exists()


@pytest.mark.parametrize("unsafe", ["mode", "symlink", "hardlink", "directory", "parent-mode"])
def test_lifecycle_rejects_unsafe_lock_without_system_commands(fixture, unsafe):
    config, source, home, calls, _ = fixture
    target, plist, _ = old_install(config, home)
    directory = home / "Library/Application Support/ClawBridgeLifecycle"
    directory.mkdir(mode=0o700)
    lock = directory / f"{config.bundle_id}.lock"
    if unsafe == "symlink":
        destination = home / "unrelated"
        destination.write_text("preserve")
        lock.symlink_to(destination)
    elif unsafe == "directory":
        lock.mkdir()
    else:
        lock.touch(mode=0o600)
        if unsafe == "mode":
            lock.chmod(0o644)
        elif unsafe == "hardlink":
            (directory / "alias").hardlink_to(lock)
        else:
            directory.chmod(0o755)
    with pytest.raises(packaging.PackagingError, match="lifecycle lock"):
        packaging.install(config, source, home, timeout=0)
    with pytest.raises(packaging.PackagingError, match="lifecycle lock"):
        packaging.uninstall(config, home)
    assert calls == []
    assert (target / "old-marker").read_text() == "old"
    assert plist.read_bytes() == b"old-plist"


def test_lifecycle_lock_remains_private_and_reusable(fixture):
    config, source, home, _, _ = fixture
    old_install(config, home)
    packaging.install(config, source, home, timeout=0)
    directory = home / "Library/Application Support/ClawBridgeLifecycle"
    lock = directory / f"{config.bundle_id}.lock"
    assert directory.stat().st_mode & 0o777 == 0o700
    assert lock.stat().st_mode & 0o777 == 0o600
    inode = lock.stat().st_ino
    packaging.uninstall(config, home)
    assert lock.stat().st_ino == inode
    packaging.install(config, source, home, timeout=0)
    assert lock.stat().st_ino == inode


def test_existing_shared_parent_modes_are_preserved(fixture):
    config, source, home, _, _ = fixture
    target, plist, _ = old_install(config, home)
    target.parent.chmod(0o755)
    plist.parent.chmod(0o755)
    packaging.install(config, source, home, timeout=0)
    assert target.parent.stat().st_mode & 0o777 == 0o755
    assert plist.parent.stat().st_mode & 0o777 == 0o755


def test_symlink_ancestor_is_rejected_before_stopping(fixture):
    config, source, home, calls, _ = fixture
    actual = home / "actual-library"
    actual.mkdir()
    (home / "Library").symlink_to(actual, target_is_directory=True)
    with pytest.raises(packaging.PackagingError, match="symlink"):
        packaging.install(config, source, home, timeout=0)
    assert not any(call[0] == "launchctl" for call in calls)


def test_token_must_be_a_regular_file(tmp_path):
    with pytest.raises(packaging.PackagingError, match="regular"):
        packaging.authenticated_status(tmp_path / "unused.sock", tmp_path)


def test_interrupted_copy_leaves_old_install_untouched(fixture, monkeypatch):
    config, source, home, calls, _ = fixture
    target, plist, _ = old_install(config, home)

    def interrupted(*args, **kwargs):
        raise OSError("synthetic interrupted copy")

    monkeypatch.setattr(packaging.shutil, "copytree", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        packaging.install(config, source, home, timeout=0)
    assert (target / "old-marker").exists()
    assert plist.read_bytes() == b"old-plist"
    assert not any(call[0] == "launchctl" for call in calls)


def test_rollback_failure_is_reported(fixture, monkeypatch):
    config, source, home, _, _ = fixture
    target, _, _ = old_install(config, home)
    original = packaging.run_command

    def reject_bootstrap(argv, **kwargs):
        if argv[:2] == ["launchctl", "bootstrap"]:
            raise subprocess.CalledProcessError(5, argv)
        return original(argv, **kwargs)

    monkeypatch.setattr(packaging, "run_command", reject_bootstrap)
    with pytest.raises(packaging.PackagingError, match="rollback also failed"):
        packaging.install(config, source, home, timeout=0)
    assert (target / "old-marker").exists()


@pytest.mark.parametrize("change", [{"identity": {"bundle_id": "wrong", "version": "2.5.0", "build_id": "candidate-build"}}, {"pid": 777}, {"executable": "/not-the-installed-app"}, {"instance_id": ""}])
def test_readiness_rejects_another_instance(fixture, monkeypatch, change):
    config, source, home, _, _ = fixture
    old_install(config, home)
    status = packaging.authenticated_status(None, None)
    status.update(change)
    monkeypatch.setattr(packaging, "authenticated_status", lambda *_: status)
    with pytest.raises(packaging.PackagingError, match="readiness failed"):
        packaging.install(config, source, home, timeout=0)


def test_missing_identity_cannot_sign(fixture):
    config, source, _, calls, _ = fixture
    with pytest.raises(packaging.PackagingError, match="unavailable"):
        packaging.sign(config, source, "local", "mcp-test absent identity")
    assert not any(call[0] == "codesign" for call in calls)


def test_developer_id_signs_inside_out_with_hardened_runtime(fixture, monkeypatch):
    config, source, _, calls, _ = fixture
    library = source / "Contents/Frameworks/nested/libdemo.dylib"
    library.parent.mkdir(parents=True)
    library.write_bytes(b"\xcf\xfa\xed\xfe" + b"synthetic")
    executable = source / "Contents/MacOS" / config.name
    executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"synthetic")
    original = packaging.run_command

    def identity(argv, **kwargs):
        if argv[0] == "security":
            return subprocess.CompletedProcess(argv, 0, "1) " + "A" * 40 + ' "Developer ID Application: mcp-test (FAKE)"', "")
        return original(argv, **kwargs)

    monkeypatch.setattr(packaging, "run_command", identity)
    proof = packaging.sign(config, source, "developer-id", "Developer ID Application: mcp-test (FAKE)")
    signing = [call for call in calls if "--sign" in call]
    assert [call[-1] for call in signing] == [str(library), str(executable), str(source)]
    assert all("--deep" not in call and "--timestamp" in call and "runtime" in call for call in signing)
    assert any(call[:4] == ["codesign", "--verify", "--deep", "--strict"] for call in calls)
    assert json.loads(proof.read_text())["build_id"] == "candidate-build"


def test_local_signing_does_not_enable_hardened_runtime(fixture, monkeypatch):
    config, source, _, calls, _ = fixture
    original = packaging.run_command

    def identity(argv, **kwargs):
        if argv[0] == "security":
            return subprocess.CompletedProcess(argv, 0, "1) " + "B" * 40 + ' "mcp-test local"', "")
        return original(argv, **kwargs)

    monkeypatch.setattr(packaging, "run_command", identity)
    packaging.sign(config, source, "local", "mcp-test local")
    assert all("runtime" not in call and "--deep" not in call for call in calls if "--sign" in call)


def test_config_paths_and_sandbox_entitlements_are_narrow(fixture, monkeypatch):
    config, _, home, _, _ = fixture
    with pytest.raises(packaging.PackagingError, match="relative"):
        replace(config, state_directory="../escape")
    config = replace(config, apple_event_targets=("org.example.Target",), usage_description="Read and update authorised items.", sandbox_read_only_home=("Library/ExampleData",))
    profile = packaging.entitlements(config, True)
    assert profile["com.apple.security.app-sandbox"] is True
    assert profile["com.apple.security.temporary-exception.files.home-relative-path.read-only"] == ["/Library/ExampleData/"]
    assert profile["com.apple.security.temporary-exception.apple-events"] == ["org.example.Target"]
    assert not any("network" in key or "library-validation" in key for key in profile)
    state, socket_path, _ = packaging.runtime_paths(config, home, True)
    assert state == home / "Library/Containers" / config.bundle_id / "Data"
    monkeypatch.setattr(packaging, "UNIX_PATH_LIMIT", 104)
    with pytest.raises(packaging.PackagingError, match="103-byte"):
        packaging.runtime_paths(config, home / ("a" * 104), True)
    assert socket_path.name == config.socket_name


def test_configs_and_plist_versions_use_single_source():
    root = Path(__file__).resolve().parents[1]
    config = packaging.load_config(root / "packaging/macos/example.toml")
    plist = packaging.info_plist(config, "2.5.0")
    assert plist["CFBundleVersion"] == plist["CFBundleShortVersionString"] == "2.5.0"
    assert plist["CFBundleIdentifier"] == config.bundle_id


def test_shell_entrypoints_can_describe_usage_from_another_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in ("build_bridge_app.sh", "sign_bridge_app.sh", "install_bridge_launchagent.sh", "uninstall_bridge_launchagent.sh"):
        result = subprocess.run(["/bin/bash", str(root / "scripts" / name), "--help"], cwd=tmp_path, capture_output=True, text=True, check=True)
        assert "--config" in result.stdout


@pytest.mark.parametrize("mutate_source", [False, True])
def test_build_uses_locked_isolated_inputs_and_records_provenance(fixture, tmp_path, monkeypatch, mutate_source):
    config, _, _, _, _ = fixture
    root = tmp_path / "synthetic-source"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "2.5.9"\n')
    (root / "uv.lock").write_text("synthetic locked input")
    (root / ".python-version").write_text("3.12.16\n")
    source = root / "src/clawbridge/demo.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic source\n")
    config_file = root / "example.toml"
    config_file.write_text("# synthetic build configuration\n")
    output = tmp_path / "build-output"
    calls = []

    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        stdout = ""
        if "PyInstaller" in argv:
            bundle = Path(argv[argv.index("--distpath") + 1]) / f"{config.name}.app"
            (bundle / "Contents/Resources").mkdir(parents=True)
            (bundle / "Contents/MacOS").mkdir()
            (bundle / "Contents/MacOS" / config.name).write_bytes(b"synthetic frozen code")
            if mutate_source:
                source.write_text("# changed during build\n")
        elif "-c" in argv:
            stdout = json.dumps({"architecture": "arm64", "python": "3.12.16", "pyinstaller": "6.20.0", "hooks": "2026.4"})
        elif argv[0] == "git":
            stdout = "a" * 40 if "rev-parse" in argv else " M src/clawbridge/demo.py"
        elif argv == ["uv", "--version"]:
            stdout = "uv synthetic-test"
        elif argv[0] == "xcrun":
            stdout = "synthetic-sdk"
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(packaging, "run_command", command)
    monkeypatch.setattr(packaging.sys, "platform", "darwin")
    monkeypatch.setattr(packaging.platform, "machine", lambda: "arm64")
    if mutate_source:
        with pytest.raises(packaging.PackagingError, match="inputs changed"):
            packaging.build(config, config_file, root, output, True)
        assert not (output / f"{config.name}.app").exists()
    else:
        bundle = packaging.build(config, config_file, root, output, True)
        manifest = json.loads((bundle / "Contents/Resources/build-manifest.json").read_text())
        assert manifest["version"] == "2.5.9"
        assert manifest["source_revision"] == "a" * 40
        assert manifest["source_dirty"] is True
        assert manifest["lock_sha256"] == packaging.digest(root / "uv.lock")
        assert manifest["source_inputs_sha256"]["src/clawbridge/demo.py"] == packaging.digest(source)
        assert manifest["entitlements"] == {"com.apple.security.app-sandbox": True}
        before = len(calls)
        with pytest.raises(packaging.PackagingError, match="Output already exists"):
            packaging.build(config, config_file, root, output, True)
        assert len(calls) == before
    sync, options = calls[0]
    assert sync == ["uv", "sync", "--locked", "--no-default-groups", "--group", "build", "--python", "3.12.16"]
    assert Path(options["env"]["UV_PROJECT_ENVIRONMENT"]).is_relative_to(output)
    assert options["cwd"] == root
    assert not any(command[0] in {"launchctl", "security", "codesign"} for command, _ in calls)
