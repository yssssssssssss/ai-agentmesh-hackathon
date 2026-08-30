#!/usr/bin/env python3
"""Validate the governed Skill Matrix and print a machine-readable report."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agentmesh.canonical_json import strict_json_loads  # noqa: E402
from agentmesh.models import SkillSourceScope  # noqa: E402
from agentmesh.skill_runtime.parser import parse_skill_file  # noqa: E402
from agentmesh.skill_runtime.profiles import (  # noqa: E402
    PILOT_BUILTIN_SKILL_NAMES,
    LoadedCapabilityProfile,
    ProfileError,
    legacy_capability_profiles,
    load_capability_profile_record,
    profile_matches_skill,
    profile_path,
)
from agentmesh.skill_runtime.trust import SkillProfileProvenanceV2  # noqa: E402

EXPECTED_DOMAIN_SKILLS = 84
EXPECTED_PLANNER_PROFILES = len(PILOT_BUILTIN_SKILL_NAMES)
EXPECTED_PROFILE_FILES = EXPECTED_DOMAIN_SKILLS
EXPECTED_DRAFT_PROFILES = EXPECTED_DOMAIN_SKILLS - EXPECTED_PLANNER_PROFILES
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


_GITHUB_HANDLE = re.compile(r"^@[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?$")
_EXPECTED_REPOSITORY = "yssssssssssss/ai-agentmesh-hackathon"


def _codeowner_entries(path: Path) -> list[tuple[str, frozenset[str]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[tuple[str, frozenset[str]]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        handles = frozenset(
            token for token in fields[1:] if _GITHUB_HANDLE.fullmatch(token)
        )
        if len(fields) >= 2 and handles:
            entries.append((fields[0], handles))
    return entries


def _codeowners_for_path(
    entries: list[tuple[str, frozenset[str]]],
    repository_path: str,
) -> frozenset[str]:
    matched = frozenset()
    for raw_pattern, handles in entries:
        pattern = raw_pattern.lstrip("/")
        if (
            pattern == "*"
            or (pattern.endswith("/") and repository_path.startswith(pattern))
            or fnmatch.fnmatchcase(repository_path, pattern)
        ):
            matched = handles
    return matched


def _provenance_blockers(
    *,
    profile_records: list[tuple[str, LoadedCapabilityProfile]],
    catalog_root: Path,
    codeowners_path: Path,
    source_manifest_path: Path,
) -> list[str]:
    try:
        manifest = SkillProfileProvenanceV2.model_validate(
            strict_json_loads(source_manifest_path.read_bytes())
        )
    except (OSError, UnicodeError, ValueError, ValidationError):
        return ["profile_provenance_v2_missing"]
    entries = {entry.skill_name: entry for entry in manifest.profiles}
    expected_names = {name for name, _loaded in profile_records}
    if (
        manifest.repository != _EXPECTED_REPOSITORY
        or len(entries) != len(manifest.profiles)
        or set(entries) != expected_names
    ):
        return ["profile_provenance_v2_invalid"]
    codeowner_entries = _codeowner_entries(codeowners_path)
    blockers: list[str] = []
    for name, loaded in profile_records:
        entry = entries[name]
        profile = loaded.profile
        sidecar = catalog_root / name / "agents" / "agentmesh.yaml"
        expected_path = sidecar.relative_to(catalog_root.parent).as_posix()
        repository_path = f"agentmesh/{expected_path}"
        codeowners = _codeowners_for_path(codeowner_entries, repository_path)
        enhanced = bool(
            profile.required_tools
            or profile.risk_level == "high"
            or profile.side_effect.value in {"local_write", "external_write"}
        )
        required_reviewers = 2 if enhanced else 1
        reviewers = tuple(dict.fromkeys(entry.reviewers))
        try:
            sidecar_hash = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        except OSError:
            blockers.append(f"profile_provenance_invalid:{name}")
            continue
        if (
            entry.profile_path != expected_path
            or entry.profile_sha256 != sidecar_hash
            or entry.reviewed_blob_sha256 != sidecar_hash
            or entry.profile_version != profile.profile_version
            or entry.profile_content_hash != profile.profile_content_hash
            or entry.skill_content_hash != profile.skill_content_hash
            or entry.reviewed_tree_sha != manifest.reviewed_tree_sha
            or entry.review_policy != ("double" if enhanced else "single")
            or len(reviewers) < required_reviewers
            or entry.author in reviewers
            or any(reviewer not in codeowners for reviewer in reviewers)
        ):
            blockers.append(f"profile_provenance_invalid:{name}")
    return blockers


def _release_review_blockers(
    *,
    profile_records: list[tuple[str, LoadedCapabilityProfile]],
    catalog_root: Path,
    roster_path: Path,
    codeowners_path: Path,
    source_manifest_path: Path,
) -> list[str]:
    blockers: list[str] = []
    approved_names = {
        name
        for name, loaded in profile_records
        if getattr(loaded, "review_state", None) == "approved"
        and getattr(loaded, "declared_planner_eligible", False)
    }
    if len(approved_names) != EXPECTED_DOMAIN_SKILLS:
        blockers.append(
            f"profiles_not_approved:{len(approved_names)}/{EXPECTED_DOMAIN_SKILLS}"
        )
    try:
        roster = yaml.safe_load(roster_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        roster = None
    roster_items = roster.get("items") if isinstance(roster, dict) else None
    if not isinstance(roster_items, list):
        blockers.append("review_roster_invalid")
    else:
        by_name = {
            item.get("skill_name"): item
            for item in roster_items
            if isinstance(item, dict) and isinstance(item.get("skill_name"), str)
        }
        if set(by_name) != {name for name, _loaded in profile_records}:
            blockers.append("review_roster_coverage_mismatch")
        today = date.today()
        for name, item in sorted(by_name.items()):
            author = item.get("author")
            reviewers = item.get("reviewers")
            required = item.get("required_reviewers")
            if (
                not isinstance(author, str)
                or not isinstance(reviewers, list)
                or not isinstance(required, int)
                or required not in {1, 2}
                or len(set(reviewers)) < required
                or author in reviewers
            ):
                blockers.append(f"review_incomplete:{name}")
                continue
            try:
                due_at = date.fromisoformat(str(item.get("review_due_at")))
                confirmed_at = date.fromisoformat(str(item.get("confirmed_at")))
            except ValueError:
                blockers.append(f"review_schedule_invalid:{name}")
                continue
            if due_at < today or confirmed_at > due_at:
                blockers.append(f"review_schedule_invalid:{name}")
    if not codeowners_path.is_file():
        blockers.append("codeowners_missing")
    blockers.extend(
        _provenance_blockers(
            profile_records=profile_records,
            catalog_root=catalog_root,
            codeowners_path=codeowners_path,
            source_manifest_path=source_manifest_path,
        )
    )
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=str(ROOT_DIR / "agentmesh" / "builtin_skills"))
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--review-roster",
        type=Path,
        default=ROOT_DIR / "docs" / "verification" / "skill-profile-review-roster.yaml",
    )
    parser.add_argument(
        "--codeowners",
        type=Path,
        default=ROOT_DIR / ".github" / "CODEOWNERS",
    )
    parser.add_argument(
        "--profile-provenance",
        type=Path,
        help="Schema-v2 build-staging Profile provenance; defaults to the catalog-root manifest path.",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    files = sorted(root.rglob("SKILL.md"))
    names: list[str] = []
    diagnostics: list[dict[str, str]] = []
    profiles = []
    profile_records: list[tuple[str, LoadedCapabilityProfile]] = []
    draft_profiles = []
    legacy_unreviewed_profiles = []
    for path in files:
        result = parse_skill_file(path, source_scope=SkillSourceScope.BUILTIN)
        if result.skill is not None:
            names.append(result.skill.name)
            sidecar = profile_path(result.skill)
            if sidecar.is_file():
                try:
                    loaded = load_capability_profile_record(result.skill)
                    profile = loaded.profile
                    profiles.append(profile)
                    profile_records.append((result.skill.name, loaded))
                    if not profile_matches_skill(profile, result.skill):
                        diagnostics.append(
                            {
                                "level": "error",
                                "code": "profile_stale",
                                "message": "Capability profile does not match the parsed Skill version and hash",
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
                    if result.skill.name in PILOT_BUILTIN_SKILL_NAMES:
                        if not profile.planner_eligible:
                            diagnostics.append(
                                {
                                    "level": "error",
                                    "code": "domain_profile_ineligible",
                                    "message": "Pilot domain Skills must remain planner eligible",
                                    "path": str(path),
                                }
                            )
                        if loaded.review_state is None:
                            legacy_unreviewed_profiles.append(result.skill.name)
                    else:
                        if loaded.review_state == "draft":
                            draft_profiles.append(result.skill.name)
                        if not args.release_gate and (
                            loaded.review_state != "draft"
                            or loaded.declared_planner_eligible
                        ):
                            diagnostics.append(
                                {
                                    "level": "error",
                                    "code": "nonpilot_profile_not_draft",
                                    "message": "Phase 1A non-Pilot Profiles must remain draft and planner-ineligible",
                                    "path": str(sidecar),
                                }
                            )
                        if not args.release_gate and profile.planner_eligible:
                            diagnostics.append(
                                {
                                    "level": "error",
                                    "code": "draft_profile_runtime_eligible",
                                    "message": "Draft Profiles cannot enter the legacy Planner",
                                    "path": str(sidecar),
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
            elif result.skill.name in PILOT_BUILTIN_SKILL_NAMES:
                diagnostics.append(
                    {
                        "level": "error",
                        "code": "pilot_profile_missing",
                        "message": "Pilot domain Skill profile is missing",
                        "path": str(sidecar),
                    }
                )
            else:
                diagnostics.append(
                    {
                        "level": "error",
                        "code": "profile_missing",
                        "message": "Every built-in Runtime Skill requires a versioned Profile sidecar",
                        "path": str(sidecar),
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
    expected_planner_profiles = (
        EXPECTED_DOMAIN_SKILLS if args.release_gate else EXPECTED_PLANNER_PROFILES
    )
    if len([profile for profile in profiles if profile.planner_eligible]) != expected_planner_profiles:
        diagnostics.append(
            {
                "level": "error",
                "code": "planner_profile_count",
                "message": (
                    f"expected {expected_planner_profiles}, loaded "
                    f"{len([profile for profile in profiles if profile.planner_eligible])}"
                ),
                "path": str(root),
            }
        )
    if len(profiles) != EXPECTED_PROFILE_FILES:
        diagnostics.append(
            {
                "level": "error",
                "code": "profile_coverage_incomplete",
                "message": f"expected {EXPECTED_PROFILE_FILES} Profile files, loaded {len(profiles)}",
                "path": str(root),
            }
        )
    expected_draft_profiles = 0 if args.release_gate else EXPECTED_DRAFT_PROFILES
    if len(draft_profiles) != expected_draft_profiles:
        diagnostics.append(
            {
                "level": "error",
                "code": "draft_profile_count",
                "message": f"expected {expected_draft_profiles}, loaded {len(draft_profiles)}",
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
    release_blockers = _release_review_blockers(
        profile_records=profile_records,
        catalog_root=root,
        roster_path=args.review_roster,
        codeowners_path=args.codeowners,
        source_manifest_path=(args.profile_provenance or root / "wiki-skill-provenance.json"),
    )
    error_count = sum(item["level"] == "error" for item in diagnostics)
    payload = {
        "root": str(root),
        "files": len(files),
        "loaded": len(names),
        "unique": len(counts),
        "planner_profiles": sum(profile.planner_eligible for profile in profiles),
        "profile_files": len(profiles),
        "profile_coverage": f"{len(profiles)}/{EXPECTED_PROFILE_FILES}",
        "draft_profiles": len(draft_profiles),
        "legacy_unreviewed_profiles": len(legacy_unreviewed_profiles),
        "legacy_profiles": len(legacy_profiles),
        "profile_versions": dict(sorted(Counter(profile.profile_version for profile in profiles).items())),
        "required_capabilities": sorted(
            {capability for profile in profiles for capability in profile.required_capabilities}
        ),
        "duplicates": domain_duplicates,
        "errors": error_count,
        "warnings": sum(item["level"] == "warning" for item in diagnostics),
        "diagnostics": diagnostics,
        "release_gate_eligible": not release_blockers and error_count == 0,
        "release_blockers": release_blockers,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["errors"] or (args.release_gate and release_blockers) else 0


if __name__ == "__main__":
    raise SystemExit(main())
