"""Read a fixed synthetic SQLite catalogue without granting request-selected paths."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from clawbridge.actions import Action
from clawbridge.protocol import ok_envelope
from clawbridge.server import BridgeRequestHandler, UnixHTTPServer, build_identity, serve_until_stopped
from clawbridge.worker import run_worker, worker_main

DEFAULT_RUNTIME = Path.home() / "Library/Application Support/ClawBridgeCatalogueBridge"
DATABASE_RELATIVE_PATH = Path("Library/Application Support/ClawBridgeCatalogue/catalogue.sqlite3")
ACTIONS = {"items": Action("items"), "search": Action("search", fields={"query": str}, required=frozenset({"query"}), nonempty=frozenset({"query"}))}


def database_path() -> Path:
    """Use the account home, even if a sandbox or launcher changes HOME."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / DATABASE_RELATIVE_PATH


@contextmanager
def open_catalogue() -> Iterator[sqlite3.Connection]:
    """Open the fixed existing file read-only, refusing symlink components."""
    path = database_path()
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ValueError("Catalogue path must not contain a symlink")
    if not path.exists():
        raise FileNotFoundError("Create the synthetic catalogue fixture before using this example")
    if not path.is_file():
        raise ValueError("Catalogue must be a regular SQLite file")
    database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        database.execute("PRAGMA query_only = ON")
        database.row_factory = sqlite3.Row
        yield database
    finally:
        database.close()


def execute(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return up to 100 rows using fixed SQL and bound search text."""
    with open_catalogue() as database:
        if name == "items":
            rows = database.execute("SELECT id, title FROM items ORDER BY id LIMIT 101").fetchall()
        elif name == "search":
            rows = database.execute("SELECT id, title FROM items WHERE instr(lower(title), lower(?)) > 0 ORDER BY id LIMIT 101", (params["query"],)).fetchall()
        else:
            raise ValueError("Unsupported catalogue action")
    return {"items": [dict(row) for row in rows[:100]], "truncated": len(rows) > 100}


class RequestHandler(BridgeRequestHandler):
    """Expose a small read-only catalogue API."""

    def resolve(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Resolve only list and search; accept no request-selected location."""
        if query:
            return None
        action = {("GET", "/catalogue/items"): "items", ("POST", "/catalogue/search"): "search"}.get((method, path))
        return (action, body) if action else None


def create_server(socket_path: Path, token_file: Path) -> UnixHTTPServer:
    """Bind the read-only adapter without a mutation or payload capture option."""
    return UnixHTTPServer(
        socket_path,
        RequestHandler,
        token_file=token_file,
        actions=ACTIONS,
        worker=lambda name, params: run_worker("clawbridge.examples.catalogue", ACTIONS[name], params),
        identity=build_identity(bundle_id="org.example.ClawBridgeCatalogue", version="0.1.0"),
    )


def main(argv: list[str] | None = None) -> int:
    """Serve catalogue reads; local health reports its path without opening it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=str(DEFAULT_RUNTIME / "bridge.sock"))
    parser.add_argument("--token-file", default=str(DEFAULT_RUNTIME / "bridge.token"))
    parser.add_argument("--worker-action", help=argparse.SUPPRESS)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args(argv)
    if args.worker_action:
        return worker_main(ACTIONS, args.worker_action, execute)
    if args.health:
        print(json.dumps(ok_envelope({"adapter": "catalogue", "database_path": str(database_path())})))
        return 0
    serve_until_stopped(create_server(Path(args.socket).expanduser(), Path(args.token_file).expanduser()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
