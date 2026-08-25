#!/usr/bin/env python3
"""Validate the governed Skill Matrix and print a machine-readable report."""

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
from agentmesh.skill_runtime.profiles import (  # noqa: E402
    PILOT_BUILTIN_SKILL_NAMES,
    ProfileError,
    legacy_capability_profiles,
    load_capability_profile,
    profile_matches_skill,
    profile_path,
)

EXPECTED_DOMAIN_SKILLS = 84
EXPECTED_PLANNER_PROFILES = len(PILOT_BUILTIN_SKILL_NAMES)
EXPECTED_LEGACY_PROFILES = 11
KNOWN_CAPABILITIES = {
    "data.query",
    "memory.project",
    "memory.search",
    "research.request",
    "risk.review",
    "wiki.corpus",
    "wiki.experiments",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=str(ROOT_DIR / "agentmesh" / "builtin_skills"))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    files = sorted(root.rglob("SKILL.md"))
    names: list[str] = []
    diagnostics: list[dict[str, str]] = []
    profiles = []
    for path in files:
        result = parse_skill_file(path, source_scope=SkillSourceScope.BUILTIN)
        if result.skill is not None:
            names.append(result.skill.name)
            if result.skill.name not in PILOT_BUILTIN_SKILL_NAMES:
                if profile_path(result.skill).is_file():
                    diagnostics.append(
                        {
                            "level": "error",
                            "code": "unexpected_nonpilot_profile",
                            "message": "Explicit-only imported Skills must not silently enter the planner",
                            "path": str(profile_path(result.skill)),
                        }
                    )
            else:
                try:
                    profile = load_capability_profile(result.skill)
                    profiles.append(profile)
                    if not profile_matches_skill(profile, result.skill):
                        diagnostics.append(
                            {
                                "level": "error",
                                "code": "profile_stale",
                                "message": "Capability profile does not match the parsed Skill version and hash",
                                "path": str(path),
                            }
                        )
                    if not profile.planner_eligible:
                        diagnostics.append(
                            {
                                "level": "error",
                                "code": "domain_profile_ineligible",
                                "message": "Pilot domain Skills must be planner eligible",
                                "path": str(path),
                            }
                        )
                    unknown = sorted(set(profile.required_capabilities) - KNOWN_CAPABILITIES)
                    if unknown:
                        diagnostics.append(
                            {
                                "level": "error",
                                "code": "unknown_profile_capability",
                                "message": ", ".join(unknown),
                                "path": str(path),
                            }
                        )
                except ProfileError as error:
                    diagnostics.append(
                        {
                            "level": "error",
                            "code": str(error),
                            "message": "Capability profile could not be loaded",
                            "path": str(path),
                        }
                    )
        diagnostics.extend(
            {"level": item.level, "code": item.code, "message": item.message, "path": item.path}
            for item in result.diagnostics
        )
    counts = Counter(names)
    legacy_profiles = legacy_capability_profiles()
    legacy_names = Counter(profile.skill_name for profile in legacy_profiles)
    domain_duplicates = {name: count for name, count in sorted(counts.items()) if count > 1}
    if domain_duplicates:
        diagnostics.append(
            {
                "level": "error",
                "code": "duplicate_domain_skill",
                "message": ", ".join(domain_duplicates),
                "path": str(root),
            }
        )
    if len(names) != EXPECTED_DOMAIN_SKILLS or len(counts) != EXPECTED_DOMAIN_SKILLS:
        diagnostics.append(
            {
                "level": "error",
                "code": "domain_skill_count",
                "message": f"expected {EXPECTED_DOMAIN_SKILLS} unique Skills, loaded {len(counts)}",
                "path": str(root),
            }
        )
    if not set(names) >= PILOT_BUILTIN_SKILL_NAMES:
        diagnostics.append(
            {
                "level": "error",
                "code": "pilot_skill_set_mismatch",
                "message": f"missing={sorted(PILOT_BUILTIN_SKILL_NAMES - set(names))}",
                "path": str(root),
            }
        )
    if len(profiles) != EXPECTED_PLANNER_PROFILES:
        diagnostics.append(
            {
                "level": "error",
                "code": "planner_profile_count",
                "message": f"expected {EXPECTED_PLANNER_PROFILES}, loaded {len(profiles)}",
                "path": str(root),
            }
        )
    if len(legacy_profiles) != EXPECTED_LEGACY_PROFILES or any(
        profile.planner_eligible for profile in legacy_profiles
    ):
        diagnostics.append(
            {
                "level": "error",
                "code": "legacy_profile_contract",
                "message": f"expected {EXPECTED_LEGACY_PROFILES} unique planner-ineligible Legacy profiles",
                "path": "agentmesh/skill_runtime/profiles.py",
            }
        )
    if any(count > 1 for count in legacy_names.values()):
        diagnostics.append(
            {
                "level": "error",
                "code": "duplicate_legacy_profile",
                "message": "Legacy profile names must be unique",
                "path": "agentmesh/skill_runtime/profiles.py",
            }
        )
    payload = {
        "root": str(root),
        "files": len(files),
        "loaded": len(names),
        "unique": len(counts),
        "planner_profiles": len(profiles),
        "legacy_profiles": len(legacy_profiles),
        "profile_versions": dict(sorted(Counter(profile.profile_version for profile in profiles).items())),
        "required_capabilities": sorted(
            {capability for profile in profiles for capability in profile.required_capabilities}
        ),
        "duplicates": domain_duplicates,
        "errors": sum(item["level"] == "error" for item in diagnostics),
        "warnings": sum(item["level"] == "warning" for item in diagnostics),
        "diagnostics": diagnostics,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
