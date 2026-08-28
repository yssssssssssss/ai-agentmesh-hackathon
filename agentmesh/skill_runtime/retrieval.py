from __future__ import annotations

import re
from dataclasses import dataclass

from agentmesh.models import (
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillDefinition,
    SkillIntent,
    SkillSideEffect,
    User,
)
from agentmesh.skill_runtime.profiles import (
    is_pilot_orchestration_skill,
    is_supported_wiki_capability,
    profile_matches_skill,
    public_tool_name,
    tool_name_for_capability,
    tool_names_for_profile,
)
from agentmesh.skill_runtime.resources import skill_wiki_corpus_ready
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.catalog import TaskCatalog
from agentmesh.task_routing.contracts import TaskRoutingResult

_SYNTHESIS_OUTPUTS = frozenset({"design_analysis", "executive_summary", "summary", "synthesis"})


@dataclass(frozen=True, slots=True)
class EligibleSkill:
    definition: SkillDefinition
    profile: SkillCapabilityProfile


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_-]*|[\u3400-\u9fff]+", text.lower()):
        terms.add(token)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            terms.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
            terms.update(token[index : index + 3] for index in range(max(0, len(token) - 2)))
    return {term for term in terms if term}


def _overlap(query: set[str], text: str) -> float:
    target = _terms(text)
    if not query or not target:
        return 0.0
    matched = query & target
    weighted = sum(min(len(term), 4) for term in matched)
    return weighted / max(1, sum(min(len(term), 4) for term in query))


class SkillCandidateRetriever:
    def __init__(self, repository: SQLiteStore, catalog: SkillCatalogService):
        self.repository = repository
        self.catalog = catalog

    def _tool_granted(self, user: User, reference: str) -> bool:
        tool_name = tool_name_for_capability(reference) or public_tool_name(reference)
        tool = next(
            (
                item
                for item in self.repository.tool_definitions
                if item.enabled and tool_name in {item.id, item.name, item.external_name}
            ),
            None,
        )
        if tool is None:
            return False
        return any(
            grant.agent_id == user.personal_agent_id and grant.tool_id == tool.id and grant.enabled
            for grant in self.repository.agent_tool_grants
        )

    def _readiness(
        self,
        user: User,
        skill: SkillDefinition,
        profile: SkillCapabilityProfile,
        intent: SkillIntent,
    ) -> list[str]:
        diagnostics: list[str] = []
        if not profile.planner_eligible:
            diagnostics.append("planner_ineligible")
        if not profile_matches_skill(profile, skill):
            diagnostics.append("profile_stale")
        if profile.side_effect == SkillSideEffect.EXTERNAL_WRITE and not intent.constraints.external_write:
            diagnostics.append("external_write_not_requested")
        for capability in profile.required_capabilities:
            if capability.startswith("wiki."):
                if (
                    not is_supported_wiki_capability(capability)
                    or not skill_wiki_corpus_ready(skill, capability)
                ):
                    diagnostics.append(f"{capability}_unavailable")
            elif (
                (tool_name := tool_name_for_capability(capability)) is None
                or not self._tool_granted(user, tool_name)
            ):
                diagnostics.append(f"{capability}_not_granted")
        for tool_reference in profile.required_tools:
            if not self._tool_granted(user, tool_reference):
                diagnostics.append(f"{tool_reference}_not_granted")
        supported_tools = self.catalog.supported_tool_names()
        for tool_reference in skill.requested_tools:
            if tool_reference not in supported_tools:
                diagnostics.append(f"{tool_reference}_unavailable")
            elif not self._tool_granted(user, tool_reference):
                diagnostics.append(f"{tool_reference}_not_granted")
        return list(dict.fromkeys(diagnostics))

    def eligible(self, user: User, intent: SkillIntent) -> tuple[list[EligibleSkill], list[str]]:
        diagnostics: list[str] = []
        eligible: list[EligibleSkill] = []
        for skill, enabled in self.catalog.list_for_agent(user.personal_agent_id):
            if not is_pilot_orchestration_skill(skill):
                continue
            profile = self.repository.get_skill_capability_profile(skill.id)
            if profile is None:
                continue
            if not enabled:
                diagnostics.extend(
                    f"{skill.name}:{capability}_unavailable"
                    for capability in profile.required_capabilities
                    if capability.startswith("wiki.") and not skill_wiki_corpus_ready(skill, capability)
                )
                continue
            reasons = self._readiness(user, skill, profile, intent)
            if reasons:
                diagnostics.extend(f"{skill.name}:{reason}" for reason in reasons)
                continue
            eligible.append(EligibleSkill(skill, profile))
        return eligible, diagnostics

    def recommend(self, user: User, intent: SkillIntent, *, limit: int = 12) -> tuple[list[SkillCandidate], list[str]]:
        eligible, diagnostics = self.eligible(user, intent)
        if not eligible:
            return [], diagnostics
        explicit = {name.removeprefix("$") for name in intent.explicit_skill_names}
        if explicit:
            eligible = [item for item in eligible if item.definition.name in explicit]
        allowed_ids = {item.definition.id for item in eligible}
        fts_ids, vector_ids, search_diagnostics = self.repository.rank_skill_profiles(intent.goal, allowed_ids)
        diagnostics.extend(search_diagnostics)
        fts_rank = {skill_id: index for index, skill_id in enumerate(fts_ids)}
        vector_rank = {skill_id: index for index, skill_id in enumerate(vector_ids)}
        query_terms = _terms(" ".join([intent.goal, *intent.input_kinds, *intent.deliverables]))
        recent_counts: dict[str, int] = {}
        for event in self.repository.audit_events:
            if event.action != "sdk_skill_activated":
                continue
            recent_counts[event.target_id] = recent_counts.get(event.target_id, 0) + 1

        candidates: list[SkillCandidate] = []
        for item in eligible:
            skill = item.definition
            profile = item.profile
            searchable = profile.search_text(skill.title, skill.description)
            lexical = _overlap(query_terms, searchable)
            example_match = max((_overlap(query_terms, value) for value in profile.examples), default=0.0)
            negative_match = max((_overlap(query_terms, value) for value in profile.negative_examples), default=0.0)
            score = SkillCandidateScore(
                fts=(2.5 / (1 + fts_rank[skill.id])) if skill.id in fts_rank else lexical * 1.5,
                embedding=(2.0 / (1 + vector_rank[skill.id])) if skill.id in vector_rank else 0,
                stage=2.0
                if profile.primary_stage == intent.primary_stage
                else 1.0
                if intent.primary_stage in profile.lifecycle_tags
                else 0,
                inputs=1.25 * len(set(intent.input_kinds) & set(profile.input_kinds)),
                outputs=1.5 * len(set(intent.deliverables) & set(profile.output_kinds)),
                examples=example_match * 4,
                recent_success=min(recent_counts.get(skill.id, 0), 5) * 0.1,
                negative=negative_match * 3,
            )
            score.total = round(
                score.fts
                + score.embedding
                + score.stage
                + score.inputs
                + score.outputs
                + score.examples
                + score.recent_success
                - score.negative,
                6,
            )
            reason_bits = [profile.capability_type.value, profile.primary_stage.value]
            matched_outputs = set(intent.deliverables) & set(profile.output_kinds)
            if matched_outputs:
                reason_bits.append("输出匹配：" + "、".join(sorted(matched_outputs)))
            candidates.append(
                SkillCandidate(
                    skill_id=skill.id,
                    skill_name=skill.name,
                    title=skill.title,
                    description=skill.description,
                    profile=profile,
                    score=score,
                    reason="；".join(reason_bits),
                )
            )
        candidates.sort(key=lambda candidate: (-candidate.score.total, candidate.skill_name))
        return candidates[: max(1, min(limit, 12))], list(dict.fromkeys(diagnostics))

    def recommend_for_route(
        self,
        user: User,
        intent: SkillIntent,
        routing_result: TaskRoutingResult,
        task_catalog: TaskCatalog,
        *,
        limit: int = 12,
    ) -> tuple[list[SkillCandidate], list[str]]:
        candidates, diagnostics = self.recommend(user, intent, limit=12)
        scenario_ids = [routing_result.scenario.scenario_id, *routing_result.scenario.supporting_scenarios]
        registry_skill_ids: list[str] = []
        for scenario_id in scenario_ids:
            mapping = task_catalog.get_mapping(scenario_id)
            if mapping is None:
                diagnostics.append(f"scenario_mapping_missing:{scenario_id}")
                continue
            registry_skill_ids.extend([*mapping.default_skill_ids, *mapping.optional_skill_ids])
        runtime_names: set[str] = set()
        for registry_skill_id in dict.fromkeys(registry_skill_ids):
            catalog_skill = task_catalog.get_skill(registry_skill_id)
            if catalog_skill is None:
                diagnostics.append(f"catalog_skill_missing:{registry_skill_id}")
            elif catalog_skill.runtime_skill_name is None:
                diagnostics.append(f"runtime_skill_unbound:{registry_skill_id}")
            else:
                runtime_names.add(catalog_skill.runtime_skill_name)
        registered_runtime_names = {
            skill.runtime_skill_name
            for skill in task_catalog.skills
            if skill.runtime_skill_name is not None
        }
        requested_outputs = set(intent.deliverables) - _SYNTHESIS_OUTPUTS
        filtered = [
            candidate
            for candidate in candidates
            if candidate.skill_name in runtime_names
            or (
                candidate.skill_name in registered_runtime_names
                and requested_outputs.intersection(candidate.profile.output_kinds)
            )
        ]
        available_names = {
            candidate.skill_name
            for candidate in filtered
            if candidate.skill_name in runtime_names
        }
        diagnostics.extend(
            f"runtime_skill_unavailable:{name}" for name in sorted(runtime_names - available_names)
        )
        if routing_result.evidence_requirement.external_evidence_required and not any(
            "web_research" in tool_names_for_profile(candidate.profile) for candidate in filtered
        ):
            diagnostics.append("external_evidence_capability_missing")
        return filtered[: max(1, min(limit, 12))], list(dict.fromkeys(diagnostics))
