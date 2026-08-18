#!/usr/bin/env python3
"""Prune old high-volume SDK stream deltas while retaining durable run outcomes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agentmesh.store import store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()
    deleted = store.prune_agent_stream_events(max(1, args.retention_days))
    print(json.dumps({"deleted": deleted, "retention_days": max(1, args.retention_days)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
