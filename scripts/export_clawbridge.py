#!/usr/bin/env python3
"""Export the public synthetic reference from an explicit source allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "export-manifest.json"
# Destination -> source. New source files are never included implicitly.
EXPORT_FILES = {
    "LICENSE": "LICENSE",
    ".python-version": ".python-version",
    **{f"src/clawbridge/{name}.py": f"src/clawbridge/{name}.py" for name in ("__init__", "actions", "protocol", "runtime", "worker", "journal", "server", "demo", "packaging")},
    **{f"tests/test_clawbridge_{name}.py": f"tests/test_clawbridge_{name}.py" for name in ("transport", "journal", "worker", "packaging")},
    **{f"scripts/{name}_bridge_{suffix}.sh": f"scripts/{name}_bridge_{suffix}.sh" for name, suffix in (("build", "app"), ("sign", "app"), ("install", "launchagent"), ("uninstall", "launchagent"))},
    "scripts/smoke_example_bridge.py": "scripts/smoke_example_bridge.py",
    "packaging/macos/bridge.toml": "packaging/macos/example.toml",
    "packaging/macos/example.toml": "packaging/macos/example.toml",
    **{f"docs/{name}": f"docs/{name}" for name in ("bridge-build.md", "adapting-clawbridge.md", "security/local-bridge-security.md")},
    **{name: f"reference/clawbridge/{name}" for name in ("pyproject.toml", "uv.lock", "pytest.ini", "tests/conftest.py", ".gitignore", ".env.example", "REFERENCE.md", ".github/workflows/check.yml")},
}


class ExportError(ValueError):
    """A source or destination failed the export contract."""


def source_metadata(source: Path) -> tuple[str, bool]:
    """Require a Git revision; hashes identify any uncommitted input changes."""
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all", "--", *sorted(set(EXPORT_FILES.values()))], capture_output=True, text=True, check=True).stdout
    return revision, bool(dirty)


def source_bytes(source: Path, relative: str) -> tuple[bytes, int]:
    """Reject links and non-files instead of following unreviewed source paths."""
    path = source
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ExportError(f"Source symlink is not exportable: {relative}")
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode):
        raise ExportError(f"Source must be a regular file: {relative}")
    return path.read_bytes(), 0o755 if mode & 0o111 else 0o644


def export_reference(source: Path, destination: Path) -> dict[str, Any]:
    """Copy reviewed bytes into an empty directory and write their provenance."""
    source = source.resolve(strict=True)
    destination = Path(os.path.abspath(destination))
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ExportError("Destination and its parents must not be symlinks")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ExportError("Destination must be absent or an empty directory")
    # Read and validate every input before creating output. The bytes hashed
    # below are the same bytes copied, even if another editor changes a source.
    inputs = {target: (relative, *source_bytes(source, relative)) for target, relative in sorted(EXPORT_FILES.items())}
    revision, dirty = source_metadata(source)
    manifest: dict[str, Any] = {"format_version": 1, "source_repository": "https://github.com/rossshannon/Things3-MCP", "source_revision": revision, "source_dirty": dirty, "files": {}}
    destination.mkdir(parents=True, exist_ok=True)
    for target, (relative, content, mode) in inputs.items():
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(mode)
        manifest["files"][target] = {"source": relative, "sha256": hashlib.sha256(content).hexdigest(), "mode": format(mode, "04o")}
    with (destination / MANIFEST_NAME).open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    """Export without installing, building, publishing or changing a repository."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New or empty directory; existing files are never replaced")
    args = parser.parse_args()
    try:
        manifest = export_reference(SOURCE_ROOT, args.destination)
    except (OSError, ExportError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Export failed: {error}\n")
    print(f"Exported {len(manifest['files'])} files from {manifest['source_revision']}; source_dirty={manifest['source_dirty']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
