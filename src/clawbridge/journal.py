"""Bounded private mutation records for inspection, never automatic replay."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .actions import MAX_BODY_BYTES, correlation_id
from .protocol import OUTCOMES, now_iso
from .runtime import atomic_write, private_directory, private_open, sync_directory

RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_RECORDS = 1000
MAX_BYTES = 10 * 1024 * 1024
COMPLETION_RESERVE = 1024


class JournalError(ValueError):
    """No durable journal admission is available; app execution must not start."""


class Journal:
    """Persist metadata before dispatch and retain bounded recovery history."""

    def __init__(self, directory: Path, *, capture_payloads: bool = False, max_records: int = MAX_RECORDS, max_bytes: int = MAX_BYTES, retention_seconds: int = RETENTION_SECONDS) -> None:
        """Load records and conservatively mark interrupted dispatches unknown."""
        private_directory(directory)
        self.directory = directory
        self.capture_payloads = capture_payloads
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.retention_seconds = retention_seconds
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, Any]] = {}
        self.active: set[str] = set()
        for path in directory.iterdir():
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                # Interrupted atomic writes are private but are not accepted records.
                fd = private_open(path, os.O_RDONLY)
                os.close(fd)
                path.unlink()
                continue
            try:
                if path.suffix != ".json" or str(uuid.UUID(path.stem)) != path.stem:
                    raise JournalError("Unexpected journal entry")
                fd = private_open(path, os.O_RDONLY)
                with os.fdopen(fd, "rb") as source:
                    raw = source.read(MAX_BODY_BYTES + 4097)
                if len(raw) > MAX_BODY_BYTES + 4096:
                    raise JournalError("Oversized journal record")
                record = json.loads(raw)
                if not isinstance(record, dict) or record.get("operation_id") != path.stem or record.get("outcome") not in OUTCOMES | {"dispatched"}:
                    raise JournalError("Invalid journal record")
                if type(record.get("created_epoch")) not in {int, float}:
                    raise JournalError("Invalid journal timestamp")
                correlation_id(record.get("correlation_id"))
                self.records[path.stem] = record
            except (ValueError, TypeError) as exc:
                raise JournalError("Journal could not be validated") from exc
        for record in self.records.values():
            if record["outcome"] == "dispatched":
                record.update(outcome="outcome_unknown", error_code="bridge_interrupted", updated_at=now_iso())
                self._persist(record)
        self._prune(0, 0)

    @staticmethod
    def _encoded(record: dict[str, Any]) -> bytes:
        return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    def _persist(self, record: dict[str, Any]) -> None:
        atomic_write(self.directory / f"{record['operation_id']}.json", self._encoded(record))

    def _prune(self, extra_records: int, extra_bytes: int) -> None:
        cutoff = time.time() - self.retention_seconds
        candidates = sorted((r for key, r in self.records.items() if key not in self.active), key=lambda r: (r["created_epoch"], r["operation_id"]))
        total = sum(len(self._encoded(r)) for r in self.records.values()) + len(self.active) * COMPLETION_RESERVE
        for record in candidates:
            over_limit = len(self.records) + extra_records > self.max_records or total + extra_bytes > self.max_bytes
            if record["created_epoch"] >= cutoff and not over_limit:
                continue
            key = record["operation_id"]
            (self.directory / f"{key}.json").unlink(missing_ok=True)
            sync_directory(self.directory)
            total -= len(self._encoded(record))
            del self.records[key]
        if len(self.records) + extra_records > self.max_records or total + extra_bytes > self.max_bytes:
            raise JournalError("Recovery storage is full")

    def start(self, action: str, params: dict[str, Any], correlation: str | None) -> str:
        """Durably reserve a unique attempt before the worker may be spawned."""
        with self.lock:
            key = str(uuid.uuid4())
            record: dict[str, Any] = {"operation_id": key, "correlation_id": correlation, "action": action, "outcome": "dispatched", "created_at": now_iso(), "created_epoch": time.time()}
            if self.capture_payloads:
                record["payload"] = params
            self._prune(1, len(self._encoded(record)) + COMPLETION_RESERVE)
            self.records[key] = record
            try:
                self._persist(record)
            except (OSError, ValueError):
                # Account for a file that may have reached rename before fsync
                # failed, so repeated failed admissions cannot bypass retention.
                record.update(outcome="not_started", error_code="journal_unavailable")
                raise
            self.active.add(key)
            return key

    def finish(self, key: str, response: dict[str, Any]) -> None:
        """Record only the outcome, static error code and a bounded object ID."""
        with self.lock:
            record = dict(self.records[key])
            record.update(outcome=response["outcome"], updated_at=now_iso())
            if not response.get("ok"):
                record["error_code"] = response.get("error_code", "worker_failed")[:96]
            data = response.get("data")
            if isinstance(data, dict):
                result_id = data.get("id", data.get("uuid"))
                if isinstance(result_id, str) and len(result_id) <= 128:
                    record["result_id"] = result_id
            try:
                self._persist(record)
            finally:
                # Even if disk persistence fails, inspection in this process retains
                # what was actually observed; a restart treats its start as unknown.
                self.records[key] = record
                self.active.discard(key)

    def lookup(self, key: str) -> dict[str, Any] | None:
        """Read one recent attempt without executing it."""
        with self.lock:
            self._prune(0, 0)
            record = self.records.get(key)
            return dict(record) if record is not None else None

    def recent(self, *, correlation: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        """Return bounded metadata, omitting full payloads from list responses."""
        if not 1 <= limit <= 100:
            raise ValueError("Operation limit must be between 1 and 100")
        with self.lock:
            self._prune(0, 0)
            records = sorted(self.records.values(), key=lambda r: (r["created_epoch"], r["operation_id"]), reverse=True)
            matches = [record for record in records if correlation is None or record["correlation_id"] == correlation]
            return [{k: v for k, v in record.items() if k != "payload"} for record in matches[:limit]]
