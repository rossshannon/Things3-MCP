"""Small adapters keep app commands and database access fixed and testable."""

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawbridge.actions import InvalidRequestError
from clawbridge.examples import catalogue, music
from clawbridge.packaging import entitlements, load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("action", "output"), [("state", "paused"), ("play", "ok"), ("pause", "ok")])
def test_music_uses_only_static_targeted_scripts_through_stdin(monkeypatch, action, output):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=output + "\n", stderr="")

    monkeypatch.setattr(music.subprocess, "run", run)
    result = music.execute(action, {})
    argv, options = calls[0]
    assert argv == ["/usr/bin/osascript"]
    assert 'application id "com.apple.Music"' in options["input"]
    assert "System Events" not in options["input"]
    assert options["timeout"] < 30
    assert options["check"] is False
    assert len(calls) == 1
    if action == "state":
        assert result == {"state": "paused"}
    else:
        assert result == {"action": action, "accepted": True}


def test_music_state_does_not_need_to_start_a_closed_app(monkeypatch):
    def run(argv, **kwargs):
        assert 'if application id "com.apple.Music" is running then' in kwargs["input"]
        return subprocess.CompletedProcess(argv, 0, stdout="not_running\n", stderr="")

    monkeypatch.setattr(music.subprocess, "run", run)
    assert music.execute("state", {}) == {"state": "not_running"}


def test_music_denied_automation_is_a_known_failure_without_private_details(monkeypatch):
    monkeypatch.setattr(music.subprocess, "run", lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, stdout="", stderr="private track: not authorised (-1743)"))
    with pytest.raises(music.AutomationDeniedError) as error:
        music.execute("play", {})
    assert error.value.outcome == "failed"
    assert error.value.error_code == "automation_denied"
    assert "Music" in error.value.authorization_hint
    assert "private track" not in str(error.value)


@pytest.mark.parametrize("result", [subprocess.CompletedProcess([], 1, stdout="", stderr="private detail"), subprocess.CompletedProcess([], 0, stdout="unexpected", stderr="")])
def test_music_does_not_claim_success_from_an_unexpected_reply(monkeypatch, result):
    monkeypatch.setattr(music.subprocess, "run", lambda *_args, **_kwargs: result)
    with pytest.raises(RuntimeError) as error:
        music.execute("play", {})
    assert not hasattr(error.value, "outcome")
    assert "private detail" not in str(error.value)


@pytest.mark.parametrize(
    ("module", "action", "params"),
    [(music, "play", {"script": "anything"}), (music, "state", {"target": "com.apple.finder"}), (catalogue, "items", {"path": "/elsewhere"}), (catalogue, "search", {"query": "ok", "sql": "DELETE FROM items"})],
)
def test_examples_reject_caller_code_targets_and_paths(module, action, params):
    with pytest.raises(InvalidRequestError):
        module.ACTIONS[action].validate(params)


@pytest.fixture
def catalogue_file(tmp_path, monkeypatch):
    home = tmp_path / "account-home"
    path = home / "Library/Application Support/ClawBridgeCatalogue/catalogue.sqlite3"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(catalogue.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(home)))
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE items (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
        database.executemany("INSERT INTO items VALUES (?, ?)", [("a", "Alpha book"), ("b", "An O'Brien book"), ("c", "100% useful")])
    return path


def test_catalogue_uses_account_home_and_a_fixed_read_only_database(catalogue_file, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "different-home"))
    assert catalogue.database_path() == catalogue_file
    before = hashlib.sha256(catalogue_file.read_bytes()).hexdigest()
    assert catalogue.execute("items", {}) == {"items": [{"id": "a", "title": "Alpha book"}, {"id": "b", "title": "An O'Brien book"}, {"id": "c", "title": "100% useful"}], "truncated": False}
    with catalogue.open_catalogue() as database:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            database.execute("DELETE FROM items")
    assert hashlib.sha256(catalogue_file.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in catalogue_file.parent.iterdir()) == ["catalogue.sqlite3"]


def test_catalogue_search_treats_quotes_and_wildcards_as_data(catalogue_file):
    assert catalogue.execute("search", {"query": "o'brien"})["items"] == [{"id": "b", "title": "An O'Brien book"}]
    assert catalogue.execute("search", {"query": "%"})["items"] == [{"id": "c", "title": "100% useful"}]
    assert catalogue.execute("search", {"query": "' OR 1=1 --"})["items"] == []


def test_catalogue_reports_bounded_results(catalogue_file):
    with sqlite3.connect(catalogue_file) as database:
        database.executemany("INSERT INTO items VALUES (?, ?)", [(f"extra-{index:03}", f"Book {index}") for index in range(101)])
    result = catalogue.execute("items", {})
    assert len(result["items"]) == 100
    assert result["truncated"] is True
    assert [item["id"] for item in result["items"]] == sorted(item["id"] for item in result["items"])


@pytest.mark.parametrize("component", ["file", "directory"])
def test_catalogue_rejects_symlink_components(catalogue_file, tmp_path, component):
    original = catalogue_file if component == "file" else catalogue_file.parent
    moved = tmp_path / "moved"
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=component == "directory")
    with pytest.raises(ValueError, match="symlink"):
        catalogue.execute("items", {})


def test_missing_catalogue_is_not_created(catalogue_file):
    catalogue_file.unlink()
    with pytest.raises(FileNotFoundError):
        catalogue.execute("items", {})
    assert not catalogue_file.exists()


@pytest.mark.parametrize(
    ("module", "path", "action", "body"),
    [
        (music, "/music/state", "state", {}),
        (music, "/music/play", "play", {}),
        (music, "/music/pause", "pause", {}),
        (catalogue, "/catalogue/items", "items", {}),
        (catalogue, "/catalogue/search", "search", {"query": "book"}),
    ],
)
def test_example_routes_are_fixed(module, path, action, body):
    handler = object.__new__(module.RequestHandler)
    method = "GET" if action in {"state", "items"} else "POST"
    assert handler.resolve(method, path, {}, body) == (action, body)
    assert handler.resolve(method, path, {"path": ["elsewhere"]}, body) is None
    assert handler.resolve(method, "/execute", {}, body) is None


@pytest.mark.parametrize("module", [music, catalogue])
def test_health_cli_never_contacts_apps_or_opens_a_database(module, monkeypatch, capsys, tmp_path):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Health must not access the app")

    monkeypatch.setattr(module, "execute", forbidden)
    monkeypatch.setattr(catalogue.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(tmp_path)))
    assert module.main(["--health"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["adapter"] in {"music", "catalogue"}
    if module is catalogue:
        assert data["database_path"] == str(tmp_path / "Library/Application Support/ClawBridgeCatalogue/catalogue.sqlite3")


def test_example_entitlements_declare_only_their_needed_capabilities():
    music_config = load_config(ROOT / "packaging/macos/music.toml")
    catalogue_config = load_config(ROOT / "packaging/macos/catalogue.toml")
    assert entitlements(music_config, sandbox=True) == {
        "com.apple.security.app-sandbox": True,
        "com.apple.security.automation.apple-events": True,
        "com.apple.security.scripting-targets": {"com.apple.Music": ["com.apple.Music.playback"]},
    }
    assert entitlements(catalogue_config, sandbox=True) == {
        "com.apple.security.app-sandbox": True,
        "com.apple.security.temporary-exception.files.home-relative-path.read-only": ["/Library/Application Support/ClawBridgeCatalogue/"],
    }
    assert music_config.bundle_id != catalogue_config.bundle_id
    assert not catalogue_config.usage_description
    assert all(not action.mutation for action in catalogue.ACTIONS.values())
    assert music.ACTIONS["play"].mutation and music.ACTIONS["pause"].mutation
