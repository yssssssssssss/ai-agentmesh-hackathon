#!/usr/bin/env python3
"""Print read-only pilot metrics as JSON. Safe to run against a live database."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agentmesh.pilot_metrics import compute_pilot_metrics, load_pilot_events, open_read_only, render  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("AGENTMESH_DB_PATH", "data/agentmesh.sqlite3"))
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        with closing(open_read_only(args.db)) as connection:
            events = load_pilot_events(connection)
        print(render(compute_pilot_metrics(events, now=datetime.now(UTC), days=args.days)))
    except (FileNotFoundError, ValueError) as error:
        print(f"pilot_metrics: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
