from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from agents import OpenAIChatCompletionsModel

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory, SelectedSDKModel
from agentmesh.agent_runtime.structured_output import JSONObjectChatCompletionsModel
from agentmesh.models import AgentRunStatus, SkillSourceScope
from agentmesh.research_orchestration.compiler import (
    CompetitiveCapabilitySnapshot,
    FrozenDocument,
    FrozenModelPolicy,
    FrozenResourceSnapshot,
    FrozenSkillActor,
    FrozenTextDocument,
    FrozenToolActor,
    tool_actor_output_schema,
)
from agentmesh.research_orchestration.contracts import canonical_sha256
from agentmesh.skill_runtime.profiles import profile_matches_skill, profile_path
from agentmesh.skill_runtime.resources import resolve_skill_resource, skill_wiki_corpus_ready
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.gateway import ToolGateway

_AGENT_ID = "agent_research"
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_DELIVERABLE_SCHEMA = _PACKAGE_ROOT / "schemas" / "deliverables" / "competitive-analysis-v1.schema.json"
_EVIDENCE_POLICY = Path(__file__).resolve().parent / "config" / "evidence-policy-v1.yaml"
_REVIEW_RUBRIC = (
    Path(__file__).resolve().parent / "config" / "review-rubrics" / "competitive-analysis-v1.yaml"
)

MODEL_ADAPTER_COMPATIBILITY_IDS = {
    "json_schema": "openai-agents-sdk.chat-completions.json-schema:v1",
    "json_object": "agentmesh.openai-chat-completions.json-object:v1",
}


class CapabilityResolutionError(RuntimeError):
    def __init__(self, *codes: str):
        self.codes = list(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def _json_document(path: Path) -> FrozenDocument:
    content = json.loads(path.read_text(encoding="utf-8"))
    return FrozenDocument(content=content, content_hash=canonical_sha256(content))


def _yaml_document(path: Path) -> FrozenDocument:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FrozenDocument(content=content, content_hash=canonical_sha256(content))


def _text_document(path: Path) -> FrozenTextDocument:
    content = path.read_text(encoding="utf-8")
    return FrozenTextDocument(content=content, content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest())


def frozen_model_policy(selected: SelectedSDKModel) -> FrozenModelPolicy:
    mode = selected.structured_output_mode.value
    try:
        compatibility_id = MODEL_ADAPTER_COMPATIBILITY_IDS[mode]
    except KeyError:
        raise ValueError("unsupported structured output adapter") from None
    expected_model_type = (
        JSONObjectChatCompletionsModel if mode == "json_object" else OpenAIChatCompletionsModel
    )
    if type(selected.model) is not expected_model_type:
        raise ValueError("selected model does not match its structured output adapter")
    return FrozenModelPolicy(
        requested_model_id=selected.requested_model,
        structured_output_mode=mode,
        adapter_compatibility_id=compatibility_id,
    )


class CompetitiveCapabilityResolver:
    """Resolve server-owned capability facts; callers may only supply a verified resource snapshot reference."""

    def __init__(
        self,
        repository: SQLiteStore,
        catalog: SkillCatalogService,
        tool_gateway: ToolGateway,
        model_factory: AgentMeshModelFactory | None = None,
    ):
        self.repository = repository
        self.catalog = catalog
        self.tool_gateway = tool_gateway
        self.model_factory = model_factory or AgentMeshModelFactory(repository)

    def resolve(
        self,
        *,
        run_id: str,
        user_id: str,
        resource_snapshot: FrozenResourceSnapshot,
    ) -> CompetitiveCapabilitySnapshot:
        errors: list[str] = []
        run = self.repository.get_agent_run(run_id)
        allowed_statuses = {
            AgentRunStatus.CREATED,
            AgentRunStatus.PLANNING,
            AgentRunStatus.WAITING_PLAN_APPROVAL,
        }
        if (
            run is None
            or run.orchestration_version != "research-v2"
            or not self.repository.user_can_execute_agent_run(
                user_id,
                run_id,
                allowed_statuses=allowed_statuses,
            )
        ):
            errors.append("run_not_authorized")

        selected_model: SelectedSDKModel | None = None
        user = self.repository.get_user(user_id)
        if user is None:
            errors.append("model_principal_unavailable")
        else:
            try:
                selected_model = self.model_factory.for_user(user)
            except ValueError:
                errors.append("model_configuration_invalid")
        model_policy: FrozenModelPolicy | None = None
        if selected_model is None:
            if user is not None and "model_configuration_invalid" not in errors:
                errors.append("model_runtime_unavailable")
        else:
            try:
                model_policy = frozen_model_policy(selected_model)
            except ValueError:
                errors.append("model_configuration_invalid")

        skills = [item for item in self.repository.skill_definitions if item.name == "competitive-analysis"]
        if len(skills) != 1:
            errors.append("skill_not_unique")
            raise CapabilityResolutionError(*errors)
        skill = skills[0]
        bindings = [
            item
            for item in self.repository.list_agent_skill_bindings(_AGENT_ID)
            if item.skill_id == skill.id
        ]
        if len(bindings) > 1:
            errors.append("skill_binding_not_unique")
        binding = bindings[0] if len(bindings) == 1 else None
        binding_enabled = binding is None or binding.enabled
        profile = self.catalog.get_profile(skill.id)
        if (
            not skill.enabled
            or skill.source_scope != SkillSourceScope.BUILTIN
            or not binding_enabled
            or not skill_wiki_corpus_ready(skill)
        ):
            errors.append("skill_not_eligible")
        if profile is None or not profile_matches_skill(profile, skill) or not profile.planner_eligible:
            errors.append("skill_profile_not_current")

        skill_document: FrozenTextDocument | None = None
        profile_document: FrozenTextDocument | None = None
        input_schema: FrozenDocument | None = None
        output_schema: FrozenDocument | None = None
        if profile is not None:
            try:
                skill_document = _text_document(Path(skill.source_path))
                profile_document = _text_document(profile_path(skill))
                input_path = resolve_skill_resource(skill, profile.input_schema_ref or "")
                output_path = resolve_skill_resource(skill, profile.output_schema_ref or "")
                if input_path is None or output_path is None:
                    raise OSError("Skill schema is outside the approved package")
                input_schema = _json_document(input_path)
                output_schema = _json_document(output_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                errors.append("skill_control_document_unavailable")

        manifest = resource_snapshot.manifest.content
        files = manifest.get("files", []) if isinstance(manifest, dict) else []
        for item in files if isinstance(files, list) else []:
            path = resolve_skill_resource(skill, str(item.get("path", ""))) if isinstance(item, dict) else None
            if path is None:
                errors.append("resource_snapshot_unresolvable")
                break
            content = path.read_bytes()
            if (
                item.get("content_hash") != hashlib.sha256(content).hexdigest()
                or item.get("size_bytes") != len(content)
            ):
                errors.append("resource_snapshot_drifted")
                break

        tool = self.repository.get_tool_definition("tool_web_research")
        grants = [
            item
            for item in self.repository.list_agent_tool_grants(_AGENT_ID)
            if item.tool_id == "tool_web_research"
        ]
        if len(grants) != 1:
            errors.append("tool_grant_not_unique")
        grant = grants[0] if len(grants) == 1 else None
        descriptor = self.tool_gateway.describe("web_research")
        if tool is None or not tool.enabled or grant is None or not grant.enabled:
            errors.append("tool_not_authorized")
        if descriptor is None:
            errors.append("tool_runtime_unregistered")
        elif descriptor.execution_mode != "real":
            errors.append("tool_runtime_not_real")
        elif descriptor.health_state != "healthy":
            errors.append("tool_runtime_unhealthy")
        if tool is not None and (
            tool.side_effect != "read"
            or tool.output_schema is None
            or tool.implementation_id is None
            or tool.evidence_class != "provider_summary"
        ):
            errors.append("tool_manifest_incomplete")
        if tool is not None and descriptor is not None and (
            tool.implementation_id != descriptor.implementation_id
            or tool.implementation_version != descriptor.implementation_version
        ):
            errors.append("tool_runtime_incompatible")

        try:
            deliverable_contract = _json_document(_DELIVERABLE_SCHEMA)
            evidence_policy = _yaml_document(_EVIDENCE_POLICY)
            review_rubric = _yaml_document(_REVIEW_RUBRIC)
        except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError, ValueError):
            errors.append("research_policy_unavailable")
            deliverable_contract = evidence_policy = review_rubric = None

        if errors:
            raise CapabilityResolutionError(*errors)
        assert run is not None
        assert profile is not None
        assert skill_document is not None and profile_document is not None
        assert input_schema is not None and output_schema is not None
        assert tool is not None and tool.output_schema is not None
        assert grant is not None and descriptor is not None
        assert model_policy is not None
        assert deliverable_contract is not None and evidence_policy is not None and review_rubric is not None
        try:
            published_schema = tool_actor_output_schema(input_schema.content)
        except ValueError:
            raise CapabilityResolutionError("skill_evidence_input_schema_missing") from None
        return CompetitiveCapabilitySnapshot(
            resolved_for_agent_id=_AGENT_ID,
            resolved_at=datetime.now(UTC),
            model_policy=model_policy,
            skill=FrozenSkillActor(
                skill_id=skill.id,
                skill_name="competitive-analysis",
                skill_version=skill.version,
                skill_content_hash=skill.content_hash,
                profile_content_hash=profile.profile_content_hash,
                binding_id=binding.id if binding is not None else None,
                enabled=skill.enabled,
                binding_enabled=binding_enabled,
                planner_eligible=profile.planner_eligible,
                task_types=profile.task_types,
                archetypes=profile.archetypes,
                required_tools=profile.required_tools,
                required_resources=profile.required_resources,
                input_schema_ref=profile.input_schema_ref or "",
                output_schema_ref=profile.output_schema_ref or "",
                produces_factual_claims=profile.produces_factual_claims,
                report_policy=profile.report_policy,
                instructions=skill_document,
                profile=profile_document,
                input_schema=input_schema,
                output_schema=output_schema,
            ),
            tool=FrozenToolActor(
                tool_id="tool_web_research",
                tool_name="web_research",
                implementation_id=descriptor.implementation_id,
                implementation_version=descriptor.implementation_version,
                execution_mode=descriptor.execution_mode,
                enabled=tool.enabled,
                granted=grant.enabled,
                grant_id=grant.id,
                granted_to_agent_id=_AGENT_ID,
                health_state=descriptor.health_state,
                health_checked_at=descriptor.health_checked_at,
                health_ttl_seconds=tool.health_ttl_seconds,
                side_effect="read",
                idempotency_support=tool.idempotency_support,
                approval_required=tool.approval_required,
                evidence_class="provider_summary",
                timeout_seconds=max(1, min(300, round(tool.timeout_seconds))),
                input_schema=FrozenDocument(
                    content=tool.input_schema,
                    content_hash=canonical_sha256(tool.input_schema),
                ),
                output_schema=FrozenDocument(
                    content=tool.output_schema,
                    content_hash=canonical_sha256(tool.output_schema),
                ),
                published_output_schema=FrozenDocument(
                    content=published_schema,
                    content_hash=canonical_sha256(published_schema),
                ),
            ),
            resource_snapshot=resource_snapshot,
            deliverable_contract=deliverable_contract,
            evidence_policy=evidence_policy,
            review_rubric=review_rubric,
        )
