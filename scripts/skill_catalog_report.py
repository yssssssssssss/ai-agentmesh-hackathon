#!/usr/bin/env python3
"""Print a JSON Agent Skills compatibility report without modifying the catalog."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agentmesh.models import SkillSourceScope  # noqa: E402
from agentmesh.skill_runtime.parser import parse_skill_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    files = sorted(root.rglob("SKILL.md"))
    names: list[str] = []
    diagnostics: list[dict[str, str]] = []
    for path in files:
        result = parse_skill_file(path, source_scope=SkillSourceScope.WORKSPACE)
        if result.skill is not None:
            names.append(result.skill.name)
        diagnostics.extend(
            {"level": item.level, "code": item.code, "message": item.message, "path": item.path}
            for item in result.diagnostics
        )
    counts = Counter(names)
    payload = {
        "root": str(root),
        "files": len(files),
        "loaded": len(names),
        "unique": len(counts),
        "duplicates": {name: count for name, count in sorted(counts.items()) if count > 1},
        "errors": sum(item["level"] == "error" for item in diagnostics),
        "warnings": sum(item["level"] == "warning" for item in diagnostics),
        "diagnostics": diagnostics,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
