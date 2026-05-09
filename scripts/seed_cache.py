#!/usr/bin/env python3
"""Seed the bridge cache directly via Apple Events from the running shell.

Run this from a terminal that already has Automation permission for Things 3
(e.g. Warp or Terminal.app). It writes a fresh snapshot to:

    ~/Library/Application Support/Things3-MCP/cache/latest.json

…which the MCP server's CacheThingsProvider can then serve. Useful when the
signed-bundle bridge is blocked by Tahoe TCC attribution issues but the user's
terminal still has the grants needed to read Things data via osascript / JXA.

Usage:
    uv run python scripts/seed_cache.py

If the calling terminal lacks Automation for Things 3, macOS will surface a
prompt the first time. Approve it, then re-run.
"""

from __future__ import annotations

import sys

from things3_mcp_bridge.cache import write_snapshot
from things3_mcp_bridge.db_reader import run_jxa_action


def main() -> int:
    """Run a JXA snapshot and write it to the cache."""
    print("Reading Things via Apple Events (this may prompt for Automation if first run)...", file=sys.stderr)
    data = run_jxa_action("snapshot")
    snapshot = write_snapshot(data, source="seed")
    counts = {k: len(v) if isinstance(v, list) else 0 for k, v in data.items() if not k.startswith("_")}
    print(f"Wrote cache snapshot at {snapshot['generated_at']}")
    for key in ("inbox", "today", "upcoming", "anytime", "someday", "todos", "projects", "areas", "tags"):
        if key in counts:
            print(f"  {key:10s}: {counts[key]} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
