from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.chat_skills import CHAT_SKILLS
from agentmesh.models import (
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillLifecycleStage,
    SkillSideEffect,
    SkillSourceScope,
)
from agentmesh.skill_runtime.matching import positive_skill_description

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

_INPUT_COMPATIBILITY: dict[str, frozenset[str]] = {
    "competitive_material": frozenset({"research_evidence", "competitive_analysis"}),
    "research_material": frozenset({"research_evidence", "competitive_analysis", "provider_summary"}),
    "research_findings": frozenset(
        {"research_evidence", "competitive_analysis", "jtbd_analysis", "opportunity_definition"}
    ),
    "issue_list": frozenset({"competitive_analysis", "jtbd_analysis", "opportunity_definition"}),
    "metric_context": frozenset({"prioritized_issues", "action_plan", "competitive_analysis", "jtbd_analysis"}),
}


def kinds_compatible(output_kind: str, input_kind: str) -> bool:
    return output_kind == input_kind or output_kind in _INPUT_COMPATIBILITY.get(input_kind, frozenset())


def compatible_input_kind(output_kind: str, input_kinds: list[str]) -> str | None:
    return next((input_kind for input_kind in input_kinds if kinds_compatible(output_kind, input_kind)), None)


class ProfileError(ValueError):
    pass


ProfileReviewState = Literal["draft", "approved"]
_ProfileValue = Annotated[str, Field(min_length=1, max_length=120)]
_ProfileResource = Annotated[str, Field(min_length=1, max_length=240)]
_ProfileExample = Annotated[str, Field(min_length=1, max_length=300)]
_PROFILE_DOCUMENT_MAX_BYTES = 32 * 1024
_MAX_CAPABILITY_DESCRIPTION_CHARS = 140
_MAX_CAPABILITY_CARD_BYTES = 4 * 1024
_CAPABILITY_TO_TOOL = {
    "research.request": "web_research",
    "data.query": "data_query",
    "memory.search": "memory_search",
    "memory.project": "memory_search",
    "risk.review": "risk_review",
}
_SUPPORTED_WIKI_CAPABILITIES = frozenset({"wiki.corpus", "wiki.experiments"})
_TOOL_REFERENCE_TO_NAME = {"tool_web_research": "web_research"}


class _ProfileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = "auto"
    skill_version: str = Field(min_length=1, max_length=40)
    skill_content_hash: str = Field(min_length=1, max_length=128)
    profile_version: str = Field(min_length=1, max_length=40)
    display_description: str | None = Field(default=None, max_length=100)
    primary_stage: SkillLifecycleStage
    lifecycle_tags: list[SkillLifecycleStage] = Field(default_factory=list, max_length=8)
    capability_type: SkillCapabilityType
    input_kinds: list[_ProfileValue] = Field(default_factory=list, max_length=20)
    output_kinds: list[_ProfileValue] = Field(default_factory=list, max_length=20)
    examples: list[_ProfileExample] = Field(default_factory=list, max_length=8)
    negative_examples: list[_ProfileExample] = Field(default_factory=list, max_length=8)
    required_capabilities: list[_ProfileValue] = Field(default_factory=list, max_length=20)
    task_types: list[_ProfileValue] = Field(default_factory=list, max_length=20)
    archetypes: list[_ProfileValue] = Field(default_factory=list, max_length=20)
    required_tools: list[_ProfileValue] = Field(default_factory=list, max_length=20)
    required_resources: list[_ProfileResource] = Field(default_factory=list, max_length=20)
    input_schema_ref: str | None = Field(default=None, max_length=240)
    output_schema_ref: str | None = Field(default=None, max_length=240)
    produces_factual_claims: bool = False
    report_policy: str = Field(default="never", pattern="^(never|on_request|default)$")
    cost_level: str = Field(default="low", pattern="^(low|medium|high)$")
    risk_level: str = Field(default="low", pattern="^(low|medium|high)$")
    owner: str = Field(default="platform", min_length=1, max_length=120)
    side_effect: SkillSideEffect = SkillSideEffect.READ
    review_state: ProfileReviewState | None = None
    planner_eligible: bool = True


@dataclass(frozen=True, slots=True)
class LoadedCapabilityProfile:
    profile: SkillCapabilityProfile
    review_state: ProfileReviewState | None
    declared_planner_eligible: bool


def profile_path(skill: SkillDefinition) -> Path:
    return Path(skill.source_path).parent / "agents" / "agentmesh.yaml"


def is_pilot_orchestration_skill(skill: SkillDefinition) -> bool:
    return skill.source_scope == SkillSourceScope.BUILTIN and skill.name in PILOT_BUILTIN_SKILL_NAMES


def tool_name_for_capability(capability: str) -> str | None:
    return _CAPABILITY_TO_TOOL.get(capability)


def is_supported_wiki_capability(capability: str) -> bool:
    return capability in _SUPPORTED_WIKI_CAPABILITIES


def public_tool_name(reference: str) -> str:
    return _TOOL_REFERENCE_TO_NAME.get(reference, reference)


def tool_names_for_profile(profile: SkillCapabilityProfile) -> set[str]:
    capability_tools = {
        tool_name
        for capability in profile.required_capabilities
        if (tool_name := tool_name_for_capability(capability)) is not None
    }
    declared_tools = {
        public_tool_name(reference)
        for reference in profile.required_tools
    }
    return capability_tools | declared_tools


def skill_capability_card(
    skill: SkillDefinition,
    profile: SkillCapabilityProfile | None = None,
) -> dict[str, object]:
    """Build the bounded public Skill projection shared by indexing and models."""

    description = (
        (profile.display_description if profile is not None else None)
        or skill.metadata.get("short-description")
        or positive_skill_description(skill.description)
    )
    description = " ".join(description.split())
    if len(description) > _MAX_CAPABILITY_DESCRIPTION_CHARS:
        description = (
            description[: _MAX_CAPABILITY_DESCRIPTION_CHARS - 1].rstrip("，。；：、 ")
            + "…"
        )
    raw_stage = skill.metadata.get("agentmesh-stage", "").strip()
    try:
        primary_stage = (
            profile.primary_stage.value
            if profile is not None
            else SkillLifecycleStage(raw_stage).value
        )
    except ValueError:
        primary_stage = None
    card: dict[str, object] = {
        "skill_id": skill.id,
        "name": skill.name,
        "title": skill.title,
        "description": description,
        "aliases": skill.aliases[:10],
        "primary_stage": primary_stage,
    }
    if profile is not None:
        card.update(
            {
                "lifecycle_tags": [stage.value for stage in profile.lifecycle_tags],
                "capability_type": profile.capability_type.value,
                "input_kinds": profile.input_kinds,
                "output_kinds": profile.output_kinds,
                "side_effect": profile.side_effect.value,
                "cost_level": profile.cost_level,
                "risk_level": profile.risk_level,
                "required_tools": sorted(tool_names_for_profile(profile)),
            }
        )
    if len(canonical_json_bytes(card)) > _MAX_CAPABILITY_CARD_BYTES:
        raise ValueError("capability_card_too_large")
    return card


def load_capability_profile_record(skill: SkillDefinition) -> LoadedCapabilityProfile:
    path = profile_path(skill)
    try:
        raw = path.read_bytes()
        if len(raw) > _PROFILE_DOCUMENT_MAX_BYTES:
            raise ProfileError("profile_too_large")
        payload = yaml.safe_load(raw)
        document = _ProfileDocument.model_validate(payload)
        if len(canonical_json_bytes(document.model_dump(mode="json"))) > _PROFILE_DOCUMENT_MAX_BYTES:
            raise ProfileError("profile_too_large")
    except ProfileError:
        raise
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
    profile = SkillCapabilityProfile(
        id=skill.id,
        skill_id=skill.id,
        skill_name=skill.name,
        skill_title=skill.title,
        skill_aliases=skill.aliases[:10],
        skill_version=document.skill_version,
        skill_content_hash=document.skill_content_hash,
        profile_version=document.profile_version,
        profile_content_hash=hashlib.sha256(raw).hexdigest(),
        display_description=document.display_description,
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
        planner_eligible=(
            document.planner_eligible
            and document.review_state != "draft"
        ),
    )
    try:
        skill_capability_card(skill, profile)
    except ValueError as error:
        raise ProfileError("profile_invalid") from error
    return LoadedCapabilityProfile(
        profile=profile,
        review_state=document.review_state,
        declared_planner_eligible=document.planner_eligible,
    )


def load_capability_profile(skill: SkillDefinition) -> SkillCapabilityProfile:
    return load_capability_profile_record(skill).profile


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
