from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentmesh.chat_skills import CHAT_SKILLS
from agentmesh.models import (
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillLifecycleStage,
    SkillSideEffect,
    SkillSourceScope,
)

PILOT_BUILTIN_SKILL_NAMES = frozenset(
    {
        "build-experience-metrics",
        "competitive-analysis",
        "generate-interview-guide",
        "generate-research-plan",
        "generate-survey",
        "generate-usability-test",
        "issue-prioritization",
        "jobs-to-be-done",
        "prd-feasibility",
        "query-experiment-conclusions",
    }
)


class ProfileError(ValueError):
    pass


class _ProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = "auto"
    skill_version: str = Field(min_length=1, max_length=40)
    skill_content_hash: str = Field(min_length=1, max_length=128)
    profile_version: str = Field(min_length=1, max_length=40)
    primary_stage: SkillLifecycleStage
    lifecycle_tags: list[SkillLifecycleStage] = Field(default_factory=list)
    capability_type: SkillCapabilityType
    input_kinds: list[str] = Field(default_factory=list)
    output_kinds: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    archetypes: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(default_factory=list)
    input_schema_ref: str | None = Field(default=None, max_length=240)
    output_schema_ref: str | None = Field(default=None, max_length=240)
    produces_factual_claims: bool = False
    report_policy: str = Field(default="never", pattern="^(never|on_request|default)$")
    cost_level: str = Field(default="low", pattern="^(low|medium|high)$")
    risk_level: str = Field(default="low", pattern="^(low|medium|high)$")
    owner: str = Field(default="platform", min_length=1, max_length=120)
    side_effect: SkillSideEffect = SkillSideEffect.READ
    planner_eligible: bool = True


def profile_path(skill: SkillDefinition) -> Path:
    return Path(skill.source_path).parent / "agents" / "agentmesh.yaml"


def is_pilot_orchestration_skill(skill: SkillDefinition) -> bool:
    return skill.source_scope == SkillSourceScope.BUILTIN and skill.name in PILOT_BUILTIN_SKILL_NAMES


def load_capability_profile(skill: SkillDefinition) -> SkillCapabilityProfile:
    path = profile_path(skill)
    try:
        raw = path.read_bytes()
        payload = yaml.safe_load(raw)
        document = _ProfileDocument.model_validate(payload)
    except OSError as error:
        raise ProfileError(f"profile_unavailable:{type(error).__name__}") from error
    except (yaml.YAMLError, ValidationError) as error:
        raise ProfileError("profile_invalid") from error
    if document.skill_id not in {"auto", skill.id}:
        raise ProfileError("profile_skill_id_mismatch")
    if document.skill_version != skill.version:
        raise ProfileError("profile_skill_version_mismatch")
    if document.skill_content_hash != skill.content_hash:
        raise ProfileError("profile_skill_hash_mismatch")
    lifecycle_tags = document.lifecycle_tags or [document.primary_stage]
    return SkillCapabilityProfile(
        id=skill.id,
        skill_id=skill.id,
        skill_name=skill.name,
        skill_version=document.skill_version,
        skill_content_hash=document.skill_content_hash,
        profile_version=document.profile_version,
        profile_content_hash=hashlib.sha256(raw).hexdigest(),
        primary_stage=document.primary_stage,
        lifecycle_tags=list(dict.fromkeys(lifecycle_tags)),
        capability_type=document.capability_type,
        input_kinds=document.input_kinds,
        output_kinds=document.output_kinds,
        examples=document.examples,
        negative_examples=document.negative_examples,
        required_capabilities=document.required_capabilities,
        task_types=document.task_types,
        archetypes=document.archetypes,
        required_tools=document.required_tools,
        required_resources=document.required_resources,
        input_schema_ref=document.input_schema_ref,
        output_schema_ref=document.output_schema_ref,
        produces_factual_claims=document.produces_factual_claims,
        report_policy=document.report_policy,
        cost_level=document.cost_level,
        risk_level=document.risk_level,
        owner=document.owner,
        side_effect=document.side_effect,
        planner_eligible=document.planner_eligible and is_pilot_orchestration_skill(skill),
    )


def profile_matches_skill(profile: SkillCapabilityProfile, skill: SkillDefinition) -> bool:
    return (
        profile.skill_id == skill.id
        and profile.skill_name == skill.name
        and profile.skill_version == skill.version
        and profile.skill_content_hash == skill.content_hash
    )


_LEGACY_CAPABILITIES: dict[str, tuple[SkillCapabilityType, SkillSideEffect, list[str], list[str]]] = {
    "$memory.search": (SkillCapabilityType.RETRIEVAL, SkillSideEffect.READ, ["memory_query"], ["memory_evidence"]),
    "$memory.personal": (SkillCapabilityType.RETRIEVAL, SkillSideEffect.READ, ["memory_query"], ["personal_memory"]),
    "$memory.project": (SkillCapabilityType.RETRIEVAL, SkillSideEffect.READ, ["memory_query"], ["project_memory"]),
    "$memory.team": (SkillCapabilityType.RETRIEVAL, SkillSideEffect.READ, ["memory_query"], ["team_memory"]),
    "$brief.create": (SkillCapabilityType.GENERATION, SkillSideEffect.DRAFT, ["design_requirement"], ["design_brief"]),
    "$note.save": (SkillCapabilityType.KNOWLEDGE, SkillSideEffect.LOCAL_WRITE, ["note"], ["private_memory"]),
    "$research.request": (SkillCapabilityType.RESEARCH, SkillSideEffect.READ, ["research_query"], ["research_evidence"]),
    "$data.query": (SkillCapabilityType.RETRIEVAL, SkillSideEffect.READ, ["metric_query"], ["metric_evidence"]),
    "$risk.review": (SkillCapabilityType.REVIEW, SkillSideEffect.READ, ["material"], ["risk_review"]),
    "$memory.propose": (SkillCapabilityType.KNOWLEDGE, SkillSideEffect.LOCAL_WRITE, ["finding"], ["memory_candidate"]),
    "$system.info": (SkillCapabilityType.PLATFORM, SkillSideEffect.READ, [], ["system_info"]),
}


def legacy_capability_profiles() -> list[SkillCapabilityProfile]:
    profiles: list[SkillCapabilityProfile] = []
    for spec in CHAT_SKILLS:
        capability_type, side_effect, input_kinds, output_kinds = _LEGACY_CAPABILITIES[spec.command]
        name = spec.command.removeprefix("$")
        profile_id = f"legacy:{name}"
        profiles.append(
            SkillCapabilityProfile(
                id=profile_id,
                skill_id=profile_id,
                skill_name=name,
                skill_version="1",
                skill_content_hash="legacy-v1",
                profile_version="1",
                profile_content_hash="legacy-v1",
                primary_stage=SkillLifecycleStage.PLATFORM,
                lifecycle_tags=[SkillLifecycleStage.PLATFORM],
                capability_type=capability_type,
                input_kinds=input_kinds,
                output_kinds=output_kinds,
                examples=[spec.description, spec.usage],
                negative_examples=[],
                required_capabilities=[],
                side_effect=side_effect,
                planner_eligible=False,
            )
        )
    return profiles
