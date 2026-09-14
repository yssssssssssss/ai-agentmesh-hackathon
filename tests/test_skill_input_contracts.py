from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmesh.models import SkillDefinition, SkillSourceScope, SkillUserInputMode
from agentmesh.skill_runtime.input_contracts import UserInputContractError, load_user_input_contract
from agentmesh.skill_runtime.profiles import ProfileError, load_capability_profile_record
from scripts.build_skill_input_inventory import build_inventory


def _skill(tmp_path: Path, *, name: str = "contract-fixture") -> SkillDefinition:
    root = tmp_path / name
    (root / "agents").mkdir(parents=True)
    skill_file = root / "SKILL.md"
    skill_file.write_text("# Contract fixture\n\n## Inputs\nA goal and optional data.\n", encoding="utf-8")
    return SkillDefinition(
        id=f"skill_{name}",
        name=name,
        title="Contract fixture",
        description="Contract fixture",
        instructions=skill_file.read_text(encoding="utf-8"),
        source_path=str(skill_file),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="a" * 64,
    )


def _contract(skill: SkillDefinition) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"agentmesh://skills/{skill.name}/user-input-v{skill.version}",
        "schema_version": "skill-user-input-v1",
        "type": "object",
        "required": ["goal"],
        "properties": {
            "goal": {"type": "string", "title": "目标", "minLength": 1, "maxLength": 4000},
            "data": {
                "type": "array",
                "title": "数据",
                "items": {
                    "type": "string",
                    "title": "CSV",
                    "format": "agentmesh-input-artifact",
                    "contentMediaType": "text/csv",
                    "x-agentmesh-required-columns": ["date", "value"],
                },
                "maxItems": 2,
            },
        },
        "additionalProperties": False,
    }


def _write_profile(skill: SkillDefinition, **updates: object) -> None:
    payload: dict[str, object] = {
        "skill_version": skill.version,
        "skill_content_hash": skill.content_hash,
        "profile_version": "1",
        "primary_stage": "pre_design",
        "capability_type": "analysis",
        "review_state": "approved",
        "planner_eligible": True,
        **updates,
    }
    path = Path(skill.source_path).parent / "agents" / "agentmesh.yaml"
    import yaml

    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_loads_and_hashes_bounded_user_input_contract(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    contract_path = Path(skill.source_path).parent / "user-input.schema.json"
    contract_path.write_text(json.dumps(_contract(skill)), encoding="utf-8")

    loaded = load_user_input_contract(skill, contract_path.name)

    assert loaded.contract.required == ["goal"]
    assert loaded.contract.properties["data"].artifact_spec is not None
    assert loaded.content_hash == load_user_input_contract(skill, contract_path.name).content_hash


def test_contract_rejects_remote_ref_and_out_of_root_path(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    payload = _contract(skill)
    payload["$ref"] = "https://example.com/schema.json"
    (Path(skill.source_path).parent / "user-input.schema.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(UserInputContractError, match="user_input_contract_invalid"):
        load_user_input_contract(skill, "user-input.schema.json")
    with pytest.raises(UserInputContractError, match="user_input_contract_path_invalid"):
        load_user_input_contract(skill, "../outside.json")


def test_profile_requires_a_contract_for_preflight(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    _write_profile(skill, user_input_mode="preflight")

    with pytest.raises(ProfileError, match="user_input_contract_missing"):
        load_capability_profile_record(skill)


def test_prompt_only_profile_cannot_reference_a_contract(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    _write_profile(
        skill,
        user_input_mode="prompt_only",
        user_input_schema_ref="user-input.schema.json",
    )

    with pytest.raises(ProfileError, match="user_input_contract_invalid"):
        load_capability_profile_record(skill)


def test_pilot_profile_must_be_explicitly_classified(tmp_path: Path) -> None:
    skill = _skill(tmp_path, name="build-experience-metrics")
    _write_profile(skill)

    with pytest.raises(ProfileError, match="user_input_contract_unclassified"):
        load_capability_profile_record(skill)


def test_checked_in_inventory_covers_every_callable_builtin() -> None:
    inventory = build_inventory()
    callable_skills = [
        item
        for item in inventory["skills"]
        if item["planner_eligible"] and item["profile_status"] != "draft"
    ]
    assert inventory["skill_count"] == len(inventory["skills"])
    assert inventory["callable_skill_count"] == len(callable_skills)
    assert callable_skills
    assert inventory["unclassified_callable_skills"] == []
    checked_in = json.loads(
        Path("docs/verification/skill-input-inventory.json").read_text(encoding="utf-8")
    )
    assert checked_in == inventory


def test_preflight_profile_records_contract_identity(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    (Path(skill.source_path).parent / "user-input.schema.json").write_text(
        json.dumps(_contract(skill)),
        encoding="utf-8",
    )
    _write_profile(
        skill,
        user_input_mode="preflight",
        user_input_schema_ref="user-input.schema.json",
    )

    profile = load_capability_profile_record(skill).profile

    assert profile.user_input_mode is SkillUserInputMode.PREFLIGHT
    assert profile.user_input_contract_hash is not None
