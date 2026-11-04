"""Private recovery records, limits, interruption and runtime safety."""

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from clawbridge.journal import Journal, JournalError
from clawbridge.protocol import ok_envelope
from clawbridge.runtime import RuntimeSafetyError, SocketLease, ensure_token


def test_interrupted_attempt_becomes_unknown_and_is_never_replayed(tmp_path):
    first = Journal(tmp_path / "operations")
    key = first.start("increment", {"amount": 1}, "same-label")
    restarted = Journal(tmp_path / "operations")
    assert restarted.lookup(key)["outcome"] == "outcome_unknown"
    assert restarted.lookup(key)["error_code"] == "bridge_interrupted"
    assert len(restarted.recent(correlation="same-label")) == 1


def test_payload_opt_in_and_retention_never_delete_active_records(tmp_path):
    journal = Journal(tmp_path / "operations", capture_payloads=True, max_records=1)
    first = journal.start("echo", {"text": "private-payload"}, None)
    assert journal.lookup(first)["payload"] == {"text": "private-payload"}
    assert "payload" not in journal.recent()[0]
    with pytest.raises(JournalError):
        journal.start("echo", {"text": "next"}, None)
    assert journal.lookup(first) is not None
    journal.finish(first, ok_envelope({"id": "one"}, outcome="succeeded"))
    second = journal.start("echo", {"text": "next"}, None)
    assert journal.lookup(first) is None
    assert journal.lookup(second) is not None
    assert journal.directory.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in journal.directory.iterdir())


def test_expiry_prunes_inactive_only(tmp_path, monkeypatch):
    journal = Journal(tmp_path / "operations", retention_seconds=10)
    terminal = journal.start("echo", {}, None)
    journal.finish(terminal, ok_envelope({}, outcome="succeeded"))
    active = journal.start("echo", {}, None)
    future = time.time() + 20
    monkeypatch.setattr(time, "time", lambda: future)
    assert journal.lookup(terminal) is None
    assert journal.lookup(active)["outcome"] == "dispatched"


def test_byte_budget_rejects_before_writing(tmp_path):
    journal = Journal(tmp_path / "operations", capture_payloads=True, max_bytes=1500)
    with pytest.raises(JournalError):
        journal.start("echo", {"text": "x" * 2000}, None)
    assert list(journal.directory.iterdir()) == []


def test_corrupt_record_fails_closed(tmp_path):
    journal = Journal(tmp_path / "operations")
    key = journal.start("echo", {}, None)
    (journal.directory / f"{key}.json").write_text("not json")
    with pytest.raises(JournalError):
        Journal(journal.directory)


def test_completion_contains_metadata_but_never_result_content(tmp_path):
    journal = Journal(tmp_path / "operations")
    key = journal.start("write", {"title": "private-title"}, None)
    journal.finish(key, ok_envelope({"id": "object-1", "title": "private-title", "notes": "private-notes"}, outcome="succeeded"))
    raw = (journal.directory / f"{key}.json").read_text()
    assert "private-title" not in raw and "private-notes" not in raw
    assert json.loads(raw)["result_id"] == "object-1"


def test_token_creation_is_concurrent_and_empty_existing_token_fails(tmp_path):
    path = tmp_path / "bridge.token"
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: ensure_token(path), range(16)))
    assert len(set(tokens)) == 1
    path.write_text("")
    with pytest.raises(RuntimeSafetyError):
        ensure_token(path)


def test_runtime_rejects_symlink_directory_and_public_directory(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeSafetyError):
        ensure_token(linked / "token")
    real.chmod(0o755)
    with pytest.raises(RuntimeSafetyError):
        ensure_token(real / "token")


def test_second_instance_does_not_replace_socket_or_token(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("s")
    path = tmp_path / "bridge.sock"
    lease = SocketLease(path)
    try:
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(path))
            lease.bound()
            listener.listen(1)
            inode = path.stat().st_ino
            with pytest.raises((BlockingIOError, RuntimeSafetyError)):
                SocketLease(path)
            assert path.stat().st_ino == inode
    finally:
        lease.close()


def test_uncoordinated_listener_and_regular_file_are_preserved(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("s")
    path = tmp_path / "bridge.sock"
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(1)
        with pytest.raises(RuntimeSafetyError):
            SocketLease(path)
        assert path.exists()
    path.unlink()
    path.write_text("do not delete")
    with pytest.raises(RuntimeSafetyError):
        SocketLease(path)
    assert path.read_text() == "do not delete"


def test_stale_owned_socket_is_removed(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("s")
    path = tmp_path / "bridge.sock"
    with socket.socket(socket.AF_UNIX) as abandoned:
        abandoned.bind(str(path))
    path.chmod(0o600)
    lease = SocketLease(path)
    try:
        assert not path.exists()
    finally:
        lease.close()


def test_two_socket_names_cannot_share_a_live_journal(tmp_path_factory):
    directory = tmp_path_factory.mktemp("s")
    lease = SocketLease(directory / "first.sock")
    try:
        with pytest.raises(BlockingIOError):
            SocketLease(directory / "second.sock")
    finally:
        lease.close()


def test_post_rename_admission_failure_stays_within_record_limit(tmp_path, monkeypatch):
    journal = Journal(tmp_path / "operations", max_records=1)
    original = journal._persist

    def fail_after_write(record):
        original(record)
        raise OSError("directory fsync failed")

    monkeypatch.setattr(journal, "_persist", fail_after_write)
    for _ in range(3):
        with pytest.raises(OSError):
            journal.start("write", {}, None)
    assert len(list(journal.directory.glob("*.json"))) == 1
    assert len(journal.recent()) == 1
    assert journal.recent()[0]["outcome"] == "not_started"
