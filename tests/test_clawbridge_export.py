"""The standalone export contains only reviewed public source and templates."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_export_records_exact_files_and_hashes(tmp_path):
    destination = tmp_path / "standalone"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/export_clawbridge.py"), str(destination)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((destination / "export-manifest.json").read_text())
    assert len(manifest["source_revision"]) == 40
    assert set(manifest["files"]) == {str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()} - {"export-manifest.json"}
    for relative, entry in manifest["files"].items():
        assert entry["sha256"] == hashlib.sha256((destination / relative).read_bytes()).hexdigest()
        assert (destination / relative).read_bytes() == (ROOT / entry["source"]).read_bytes()
    assert (destination / "packaging/macos/bridge.toml").read_bytes() == (ROOT / "packaging/macos/example.toml").read_bytes()
    assert not (destination / "README.md").exists()
    assert manifest["source_repository"] == "https://github.com/rossshannon/Things3-MCP"
    assert isinstance(manifest["source_dirty"], bool)
    assert not any(str(ROOT) in json.dumps(value) for value in manifest.values())
    project = tomllib.loads((destination / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == []
    assert project["project"]["optional-dependencies"]["mcp"] == ["mcp==1.30.0", "pydantic==2.14.1", "pydantic-settings==2.10.1"]
    assert project["project"]["scripts"]["clawbridge-mcp"] == "clawbridge_mcp.server:main"
    assert project["project"]["readme"] == "REFERENCE.md"
    packages = {package["name"] for package in tomllib.loads((destination / "uv.lock").read_text())["package"]}
    assert "mcp" in packages
    assert not any("things" in name for name in packages)
    source_files = sorted(path.name for path in (destination / "src").iterdir())
    assert source_files == ["clawbridge", "clawbridge_mcp"]
    for path in (destination / "src").rglob("*.py"):
        assert "things3_mcp" not in path.read_text()
    for path in (destination / "scripts").glob("*.sh"):
        assert path.stat().st_mode & 0o111
    assert (destination / "scripts/smoke_example_bridge.py").read_bytes() == (ROOT / "scripts/smoke_example_bridge.py").read_bytes()
    for relative in (
        "src/clawbridge/examples/__init__.py",
        "src/clawbridge/examples/music.py",
        "src/clawbridge/examples/catalogue.py",
        "packaging/macos/music.toml",
        "packaging/macos/catalogue.toml",
        "docs/examples/README.md",
        "docs/examples/music.md",
        "docs/examples/catalogue.md",
        "tests/test_clawbridge_examples.py",
        "tests/test_clawbridge_safety.py",
        "tests/test_clawbridge_mcp.py",
        "tests/test_clawbridge_mcp_stdio.py",
        "src/clawbridge_mcp/__init__.py",
        "src/clawbridge_mcp/server.py",
    ):
        assert (destination / relative).is_file(), relative


@pytest.fixture
def exporter():
    spec = importlib.util.spec_from_file_location("reference_export", ROOT / "scripts/export_clawbridge.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source_tree(tmp_path, exporter, monkeypatch):
    source = tmp_path / "source"
    for relative in set(exporter.EXPORT_FILES.values()):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    monkeypatch.setattr(exporter, "source_metadata", lambda _source: ("a" * 40, False))
    return source


def test_unknown_private_and_generated_files_are_excluded(source_tree, exporter, tmp_path):
    for name in (".env", "private-fixture.json", "src/clawbridge/new_unreviewed.py", "README.md", "build/private.txt"):
        path = source_tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic-private-canary")
    (source_tree / "unreviewed-link").symlink_to(source_tree / ".env")
    destination = tmp_path / "export"
    exporter.export_reference(source_tree, destination)
    assert not any("synthetic-private-canary" in path.read_text() for path in destination.rglob("*") if path.is_file())
    assert not (destination / "unreviewed-link").exists()


@pytest.mark.parametrize("kind", ["populated", "file", "symlink", "parent_symlink"])
def test_existing_destination_contents_are_never_replaced(source_tree, exporter, tmp_path, kind):
    existing = tmp_path / "existing"
    existing.mkdir()
    preserved = existing / "preserved.txt"
    preserved.write_text("preserve me")
    destination = tmp_path / "destination"
    if kind == "populated":
        destination = existing
    elif kind == "file":
        destination = preserved
    elif kind == "symlink":
        destination.symlink_to(existing, target_is_directory=True)
    else:
        destination.symlink_to(existing, target_is_directory=True)
        destination /= "nested"
    with pytest.raises(exporter.ExportError, match="Destination"):
        exporter.export_reference(source_tree, destination)
    assert preserved.read_text() == "preserve me"
    assert list(existing.iterdir()) == [preserved]


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "missing", "directory"])
def test_unsafe_source_fails_before_creating_output(source_tree, exporter, tmp_path, kind):
    source = source_tree / "src/clawbridge/demo.py"
    if kind == "parent_symlink":
        directory = source.parent
        moved = tmp_path / "moved-source"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        source.unlink()
        if kind == "file_symlink":
            source.symlink_to(source_tree / "src/clawbridge/actions.py")
        elif kind == "directory":
            source.mkdir()
    destination = tmp_path / "export"
    with pytest.raises((exporter.ExportError, FileNotFoundError)):
        exporter.export_reference(source_tree, destination)
    assert not destination.exists()


def test_unchanged_export_is_deterministic_and_accepts_empty_directory(source_tree, exporter, tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    exporter.export_reference(source_tree, first)
    exporter.export_reference(source_tree, second)
    assert (first / "export-manifest.json").read_bytes() == (second / "export-manifest.json").read_bytes()
