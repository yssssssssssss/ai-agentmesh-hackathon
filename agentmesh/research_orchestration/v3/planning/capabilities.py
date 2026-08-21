from __future__ import annotations

from collections.abc import Mapping

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_bytes, canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import (
    CatalogSkill,
    CatalogTool,
    CompetitiveTextCatalog,
    load_catalog_document,
)
from agentmesh.research_orchestration.v3.execution_plan import (
    CapabilityApprovalV3,
    CapabilityDecisionV3,
    CapabilityGapV3,
    CapabilityReasonV3,
    CapabilityResolutionV3,
    OptionalToolDecisionV3,
)
from agentmesh.research_orchestration.v3.ports import ClockPort
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.snapshots import (
    FrozenActorV3,
    FrozenDocumentV3,
    FrozenModelPolicyV3,
    ResearchControlSnapshotV3,
)
from agentmesh.research_orchestration.v3.planning.models import (
    ActorDescriptorPort,
    ActorRuntimeDescriptorV3,
    ApprovalAvailabilityPort,
    CapabilityResolutionResultV3,
    PlanningArtifactPort,
)
from agentmesh.research_orchestration.v3.planning.validation import validate_competitive_problem_graph


class CapabilityResolutionError(ValueError):
    pass


def _media_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith((".yaml", ".yml")):
        return "application/yaml"
    return "text/markdown"


def _catalog_snapshot_documents(catalog: CompetitiveTextCatalog) -> dict[str, FrozenDocumentV3]:
    supported_kinds = {
        "json_schema",
        "skill_instructions",
        "knowledge",
        "evidence_policy",
        "review_rubric",
        "report_template",
        "synthesis_prompt",
    }
    documents: dict[str, FrozenDocumentV3] = {}
    for item in catalog.documents:
        if item.kind not in supported_kinds:
            continue
        content = load_catalog_document(catalog, item.id)
        content_bytes = canonical_json_v3_bytes(content)
        documents[item.id] = FrozenDocumentV3(
            document_id=item.id,
            kind=item.kind,
            media_type=_media_type(item.path),
            content_hash=canonical_json_v3_sha256(content),
            size_bytes=len(content_bytes),
            content=content,
        )
    return documents


def _descriptor_failure_code(descriptor: ActorRuntimeDescriptorV3 | None) -> str | None:
    if descriptor is None:
        return "actor_descriptor_missing"
    if not descriptor.enabled or not descriptor.authorized:
        return "actor_inactive"
    if descriptor.health_state in {"unknown", "stale"}:
        return "actor_health_unknown"
    if descriptor.health_state != "healthy":
        return "actor_unhealthy"
    return None


class CompetitiveTextCapabilityResolver:
    """Resolves catalog actors and seals the exact planning-time control snapshot."""

    def __init__(
        self,
        *,
        descriptors: ActorDescriptorPort,
        approvals: ApprovalAvailabilityPort,
        artifacts: PlanningArtifactPort,
        clock: ClockPort,
        resolved_for_agent_id: str,
        model_policy: FrozenModelPolicyV3,
    ) -> None:
        self._descriptors = descriptors
        self._approvals = approvals
        self._artifacts = artifacts
        self._clock = clock
        self._resolved_for_agent_id = resolved_for_agent_id
        self._model_policy = model_policy

    def _tool_decision(
        self,
        *,
        run_id: str,
        tool: CatalogTool,
        descriptor: ActorRuntimeDescriptorV3 | None,
    ) -> tuple[CapabilityDecisionV3, CapabilityGapV3 | None, bool]:
        reasons: list[CapabilityReasonV3] = []
        if descriptor is None:
            reasons.append(
                CapabilityReasonV3(
                    code="core_tool_real_adapter_unavailable",
                    message="The required core Tool has no runtime descriptor.",
                    related_id=tool.id,
                )
            )
        else:
            if descriptor.actor_type != "tool" or descriptor.actor_id != tool.id:
                reasons.append(
                    CapabilityReasonV3(
                        code="core_tool_descriptor_mismatch",
                        message="The core Tool descriptor identity does not match the frozen catalog.",
                        related_id=tool.id,
                    )
                )
            if (
                descriptor.required_provider,
                descriptor.runtime_tool_definition_id,
                descriptor.runtime_gateway_name,
                descriptor.input_schema_document_id,
                descriptor.output_schema_document_id,
            ) != (
                tool.required_provider,
                tool.runtime_tool_definition_id,
                tool.runtime_gateway_name,
                "source-tavily-input-schema",
                "source-tavily-output-schema",
            ):
                reasons.append(
                    CapabilityReasonV3(
                        code="core_tool_descriptor_mismatch",
                        message="The core Tool descriptor mapping does not match the frozen catalog.",
                        related_id=tool.id,
                    )
                )
            if descriptor.execution_mode != "real":
                reasons.append(
                    CapabilityReasonV3(
                        code="core_tool_real_adapter_unavailable",
                        message="The required core Tool is not backed by a real runtime adapter.",
                        related_id=tool.id,
                    )
                )
            if not descriptor.enabled or not descriptor.authorized:
                reasons.append(
                    CapabilityReasonV3(
                        code="required_tool_inactive",
                        message="The required core Tool is not enabled and authorized.",
                        related_id=tool.id,
                    )
                )
            if descriptor.health_state in {"unknown", "stale"}:
                reasons.append(
                    CapabilityReasonV3(
                        code="required_tool_health_unknown",
                        message="The required core Tool health is not current.",
                        related_id=tool.id,
                    )
                )
            elif descriptor.health_state != "healthy":
                reasons.append(
                    CapabilityReasonV3(
                        code="required_tool_unhealthy",
                        message="The required core Tool is unhealthy.",
                        related_id=tool.id,
                    )
                )
        approval_available = self._approvals.can_request(
            run_id=run_id,
            authority=tool.approval_role,
            capability_type="tool",
            capability_id=tool.id,
        )
        if not approval_available:
            reasons.append(
                CapabilityReasonV3(
                    code="approval_unavailable",
                    message="The required owner approval gate cannot be created.",
                    related_id=tool.id,
                )
            )
        eligible = not reasons
        if eligible:
            reasons.append(
                CapabilityReasonV3(
                    code="eligible",
                    message="The real core Tool is healthy, authorized, and owner-gated.",
                    related_id=tool.id,
                )
            )
        approval = CapabilityApprovalV3(
            capability_type="tool",
            capability_id=tool.id,
            authority=tool.approval_role,
        )
        decision = CapabilityDecisionV3(
            actor_type="tool",
            actor_id=tool.id,
            status="eligible" if eligible else "rejected",
            required_approvals=(approval,),
            reasons=tuple(reasons),
            pending_inputs=(),
            optional_tool_decisions=(),
        )
        gap = None
        if not eligible:
            gap = CapabilityGapV3(
                capability_type="tool",
                capability_id=tool.id,
                code=reasons[0].code,
                message=reasons[0].message,
                required=True,
            )
        return decision, gap, eligible

    def _skill_decision(
        self,
        *,
        skill: CatalogSkill,
        descriptor: ActorRuntimeDescriptorV3 | None,
        tool_eligible: Mapping[str, bool],
        catalog: CompetitiveTextCatalog,
    ) -> tuple[CapabilityDecisionV3, CapabilityGapV3 | None, bool]:
        reasons: list[CapabilityReasonV3] = []
        failure = _descriptor_failure_code(descriptor)
        if failure is not None:
            reasons.append(
                CapabilityReasonV3(
                    code="skill_inactive" if failure != "actor_descriptor_missing" else failure,
                    message="The Skill runtime descriptor is missing or inactive.",
                    related_id=skill.id,
                )
            )
        elif descriptor is not None and (
            descriptor.actor_type != "skill" or descriptor.actor_id != skill.id
        ):
            reasons.append(
                CapabilityReasonV3(
                    code="actor_descriptor_mismatch",
                    message="The Skill descriptor identity does not match the frozen catalog.",
                    related_id=skill.id,
                )
            )
        for tool_id in skill.required_tools:
            if not tool_eligible.get(tool_id, False):
                reasons.append(
                    CapabilityReasonV3(
                        code="required_tool_missing",
                        message="A frozen required Tool is not eligible.",
                        related_id=tool_id,
                    )
                )
        excluded_ids = {item.id for item in catalog.excluded_source_capabilities}
        optional_decisions = tuple(
            OptionalToolDecisionV3(
                tool_id=tool_id,
                status="unavailable",
                reason_code="not_enabled_in_slice",
                message="The optional Tool is explicitly excluded from Competitive Text Slice 1.",
            )
            for tool_id in skill.source_optional_tools
            if tool_id in excluded_ids
        )
        if len(optional_decisions) != len(skill.source_optional_tools):
            reasons.append(
                CapabilityReasonV3(
                    code="optional_tool_scope_mismatch",
                    message="A source optional Tool is not explicitly classified by the frozen catalog.",
                    related_id=skill.id,
                )
            )
        eligible = not reasons
        if eligible:
            reasons.append(
                CapabilityReasonV3(
                    code="eligible",
                    message="The Skill and all frozen required capabilities are eligible.",
                    related_id=skill.id,
                )
            )
        tool_by_id = {item.id: item for item in catalog.actors.tools}
        approvals = tuple(
            CapabilityApprovalV3(
                capability_type="tool",
                capability_id=tool_id,
                authority=tool_by_id[tool_id].approval_role,
            )
            for tool_id in skill.required_tools
        )
        decision = CapabilityDecisionV3(
            actor_type="skill",
            actor_id=skill.id,
            status="eligible" if eligible else "rejected",
            required_approvals=approvals,
            reasons=tuple(reasons),
            pending_inputs=(),
            optional_tool_decisions=optional_decisions,
        )
        gap = None
        if not eligible:
            gap = CapabilityGapV3(
                capability_type="skill",
                capability_id=skill.id,
                code=reasons[0].code,
                message=reasons[0].message,
                required=True,
            )
        return decision, gap, eligible

    @staticmethod
    def _frozen_actor(
        descriptor: ActorRuntimeDescriptorV3,
        *,
        eligible: bool,
        catalog: CompetitiveTextCatalog,
    ) -> FrozenActorV3:
        tool = next((item for item in catalog.actors.tools if item.id == descriptor.actor_id), None)
        skill = next((item for item in catalog.actors.skills if item.id == descriptor.actor_id), None)
        return FrozenActorV3(
            actor_type=descriptor.actor_type,
            actor_id=descriptor.actor_id,
            implementation_id=descriptor.implementation_id,
            implementation_version=descriptor.implementation_version,
            execution_mode=descriptor.execution_mode,
            enabled=descriptor.enabled and descriptor.authorized,
            eligible=eligible,
            tier=tool.tier if tool is not None else None,
            approval_role=tool.approval_role if tool is not None else None,
            required_tool_ids=skill.required_tools if skill is not None else (),
            optional_tool_ids=skill.enabled_optional_tools if skill is not None else (),
            instruction_document_id=descriptor.instruction_document_id,
            input_schema_document_id=descriptor.input_schema_document_id,
            output_schema_document_id=descriptor.output_schema_document_id,
        )

    def resolve_with_snapshot(
        self,
        *,
        run_id: str,
        requirement: RequirementVersionV3,
        problem_graph: ProblemGraphV1,
        catalog: CompetitiveTextCatalog,
    ) -> CapabilityResolutionResultV3:
        if requirement.run_id != run_id or problem_graph.requirement_version_id != requirement.id:
            raise CapabilityResolutionError("capability_resolution_lineage_mismatch")
        if requirement.payload.planning_blocked:
            raise CapabilityResolutionError("requirement_clarification_required")
        validate_competitive_problem_graph(problem_graph, requirement.payload, catalog)

        documents = _catalog_snapshot_documents(catalog)
        descriptors: dict[tuple[str, str], ActorRuntimeDescriptorV3 | None] = {}
        for actor_type, actor_ids in (
            ("tool", tuple(item.id for item in catalog.actors.tools)),
            ("skill", tuple(item.id for item in catalog.actors.skills)),
            ("llm", tuple(item.id for item in catalog.actors.llm)),
            ("reviewer", tuple(item.id for item in catalog.actors.reviewers)),
        ):
            for actor_id in actor_ids:
                descriptor = self._descriptors.describe(actor_type, actor_id)  # type: ignore[arg-type]
                descriptors[(actor_type, actor_id)] = descriptor
                if descriptor is not None:
                    for document in descriptor.documents:
                        existing = documents.get(document.document_id)
                        if existing is not None and existing != document:
                            raise CapabilityResolutionError("descriptor_document_conflict")
                        documents[document.document_id] = document

        decisions: list[CapabilityDecisionV3] = []
        gaps: list[CapabilityGapV3] = []
        eligible: dict[tuple[str, str], bool] = {}
        tool_eligible: dict[str, bool] = {}
        for tool in catalog.actors.tools:
            decision, gap, is_eligible = self._tool_decision(
                run_id=run_id,
                tool=tool,
                descriptor=descriptors[("tool", tool.id)],
            )
            decisions.append(decision)
            tool_eligible[tool.id] = is_eligible
            eligible[("tool", tool.id)] = is_eligible
            if gap is not None:
                gaps.append(gap)
        for skill in catalog.actors.skills:
            decision, gap, is_eligible = self._skill_decision(
                skill=skill,
                descriptor=descriptors[("skill", skill.id)],
                tool_eligible=tool_eligible,
                catalog=catalog,
            )
            decisions.append(decision)
            eligible[("skill", skill.id)] = is_eligible
            if gap is not None:
                gaps.append(gap)
        for actor_type, actors in (("llm", catalog.actors.llm), ("reviewer", catalog.actors.reviewers)):
            for actor in actors:
                descriptor = descriptors[(actor_type, actor.id)]
                failure = _descriptor_failure_code(descriptor)
                identity_matches = descriptor is not None and (
                    descriptor.actor_type == actor_type and descriptor.actor_id == actor.id
                )
                is_eligible = failure is None and identity_matches
                eligible[(actor_type, actor.id)] = is_eligible
                if not is_eligible:
                    code = failure or "actor_descriptor_mismatch"
                    gaps.append(
                        CapabilityGapV3(
                            capability_type=actor_type,  # type: ignore[arg-type]
                            capability_id=actor.id,
                            code=code,
                            message=f"The required {actor_type} actor is unavailable for planning.",
                            required=True,
                        )
                    )

        excluded_types = {
            "playwright-page-capture": "tool",
            "competitive-app-analysis": "skill",
            "digital-human-competitive-analysis": "skill",
        }
        for excluded in catalog.excluded_source_capabilities:
            gaps.append(
                CapabilityGapV3(
                    capability_type=excluded_types[excluded.id],  # type: ignore[arg-type]
                    capability_id=excluded.id,
                    code=excluded.reason,
                    message="The source capability is explicitly excluded from Competitive Text Slice 1.",
                    required=False,
                )
            )

        frozen_actors: list[FrozenActorV3] = []
        for key, descriptor in descriptors.items():
            if descriptor is None:
                continue
            referenced_documents = {
                descriptor.input_schema_document_id,
                descriptor.output_schema_document_id,
            }
            if descriptor.instruction_document_id is not None:
                referenced_documents.add(descriptor.instruction_document_id)
            if not referenced_documents.issubset(documents):
                raise CapabilityResolutionError("actor_snapshot_document_missing")
            try:
                frozen_actors.append(
                    self._frozen_actor(descriptor, eligible=eligible.get(key, False), catalog=catalog)
                )
            except ValueError:
                # An invalid Tool mode remains a typed rejected decision, never a frozen executable actor.
                if descriptor.actor_type != "tool":
                    raise

        snapshot = ResearchControlSnapshotV3(
            schema_version="research-control-snapshot-v3",
            catalog_id="competitive-text-v1",
            catalog_hash=catalog.catalog_hash,
            resolved_for_agent_id=self._resolved_for_agent_id,
            resolved_at=self._clock.now(),
            model_policy=self._model_policy,
            actors=tuple(sorted(frozen_actors, key=lambda item: (item.actor_type, item.actor_id))),
            documents=tuple(sorted(documents.values(), key=lambda item: item.document_id)),
        )
        artifact = self._artifacts.seal_control_snapshot(run_id=run_id, snapshot=snapshot)
        resolution = CapabilityResolutionV3(
            decisions=tuple(decisions),
            gaps=tuple(gaps),
            control_snapshot_artifact=artifact,
        )
        return CapabilityResolutionResultV3(resolution=resolution, snapshot=snapshot)

    def resolve(
        self,
        *,
        run_id: str,
        requirement: RequirementVersionV3,
        problem_graph: ProblemGraphV1,
        catalog: CompetitiveTextCatalog,
    ) -> CapabilityResolutionV3:
        return self.resolve_with_snapshot(
            run_id=run_id,
            requirement=requirement,
            problem_graph=problem_graph,
            catalog=catalog,
        ).resolution
