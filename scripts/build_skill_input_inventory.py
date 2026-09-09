#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from agentmesh.models import SkillSourceScope, SkillUserInputMode
from agentmesh.skill_runtime.discovery import SkillRoot, discover_skills
from agentmesh.skill_runtime.input_contracts import load_user_input_contract
from agentmesh.skill_runtime.profiles import ProfileError, load_capability_profile_record, profile_path
from agentmesh.skill_runtime.service import BUILTIN_SKILLS_DIR

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "verification" / "skill-input-inventory.json"


def _input_notes(markdown: str) -> str:
    lines = markdown.splitlines()
    captured: list[str] = []
    active = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            active = any(token in heading for token in ("输入", "input", "材料", "data requirement"))
            continue
        if active and stripped:
            captured.append(stripped)
        if len(captured) >= 12:
            break
    return "\n".join(captured)[:1200]


def _media_types(contract: object) -> list[str]:
    payload = contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    media: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            content_type = value.get("contentMediaType")
            if isinstance(content_type, str):
                media.add(content_type)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return sorted(media)


def build_inventory() -> dict[str, object]:
    discovered = discover_skills([SkillRoot(BUILTIN_SKILLS_DIR, SkillSourceScope.BUILTIN)])
    records: list[dict[str, object]] = []
    for skill in sorted(discovered.skills.values(), key=lambda item: item.name):
        path = profile_path(skill)
        record: dict[str, object] = {
            "skill_id": f"builtin:{skill.name}",
            "skill_name": skill.name,
            "skill_version": skill.version,
            "skill_content_hash": skill.content_hash,
            "profile_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "profile_status": "missing",
            "planner_eligible": False,
            "input_kinds": [],
            "input_schema_ref": None,
            "user_input_mode": None,
            "classification": "not_ready",
            "user_input_schema_ref": None,
            "user_input_contract_hash": None,
            "required_media_types": [],
            "input_notes": _input_notes(skill.instructions),
            "diagnostic": None,
        }
        if path.is_file():
            try:
                raw_document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                record["profile_status"] = raw_document.get("review_state") or "unreviewed"
                record["planner_eligible"] = bool(raw_document.get("planner_eligible", True))
                record["input_kinds"] = raw_document.get("input_kinds") or []
                record["input_schema_ref"] = raw_document.get("input_schema_ref")
                record["user_input_mode"] = raw_document.get("user_input_mode")
                record["classification"] = raw_document.get("user_input_mode") or "not_ready"
                record["user_input_schema_ref"] = raw_document.get("user_input_schema_ref")
                loaded = load_capability_profile_record(skill)
                record["planner_eligible"] = loaded.profile.planner_eligible
                record["user_input_contract_hash"] = loaded.profile.user_input_contract_hash
                if loaded.profile.user_input_mode is SkillUserInputMode.PREFLIGHT:
                    contract = load_user_input_contract(
                        skill,
                        loaded.profile.user_input_schema_ref or "",
                    )
                    record["required_media_types"] = _media_types(contract.contract)
            except (OSError, yaml.YAMLError, ProfileError, ValueError) as error:
                record["planner_eligible"] = False
                record["classification"] = "not_ready"
                record["diagnostic"] = str(error)
        records.append(record)
    callable_records = [
        item
        for item in records
        if item["planner_eligible"] is True and item["profile_status"] != "draft"
    ]
    unclassified = [item["skill_name"] for item in callable_records if item["user_input_mode"] is None]
    return {
        "schema_version": "skill-input-inventory-v1",
        "catalog_root": str(BUILTIN_SKILLS_DIR.relative_to(ROOT)),
        "skill_count": len(records),
        "callable_skill_count": len(callable_records),
        "unclassified_callable_skills": unclassified,
        "skills": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the deterministic Skill input inventory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_inventory(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("skill input inventory is stale; regenerate it")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
