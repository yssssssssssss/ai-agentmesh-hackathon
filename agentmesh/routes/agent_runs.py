"""Durable OpenAI Agents SDK run creation, inspection, streaming, and cancellation routes."""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse

from agentmesh.agent_run_identity import (
    agent_run_create_request_hash,
    agent_run_create_request_matches,
)
from agentmesh.agent_runtime.settings import (
    SkillOrchestrationMode,
    deepsearch_enabled,
    skill_orchestration_mode,
)
from agentmesh.artifacts import (
    ArtifactAccessError,
    ArtifactAccessScope,
    DeepSearchArtifactSchemaRegistry,
    DeepSearchReportV1,
    V1ArtifactReader,
)
from agentmesh.deepsearch.admission import (
    evaluate_deepsearch_availability,
    record_deepsearch_admission_rejection,
)
from agentmesh.deepsearch.contracts import (
    DeepSearchPlanDetailResponse,
    DeepSearchPlanTransitionResponse,
    DeepSearchPlanViewV1,
    DeepSearchRetryDisposition,
)
from agentmesh.deepsearch.planning import (
    build_deepsearch_plan_snapshot,
    freeze_deepsearch_plan_resources,
    plan_content_hash,
)
from agentmesh.deepsearch.service import deepsearch_retry_disposition
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunCreateRequest,
    AgentRunEvent,
    AgentRunEventsResponse,
    AgentRunRetryRequest,
    AgentRunStatus,
    ArtifactVerificationState,
    BlockedSkillMatchPublicV1,
    ChatThread,
    ItemResponse,
    RuntimeToolCallClaimV1,
    RuntimeToolCallOutcomeV1,
    ScenarioAssignmentOptionV1,
    SkillOrchestrationRequestMode,
    SkillPlanDetailResponse,
    SkillPlanDraft,
    SkillPlanPublicView,
    SkillPlanStatus,
    SkillPlanTransitionResponse,
    SkillPlanUpdateRequest,
    SkillPlanVersionRequest,
    SkillSynthesisResult,
    User,
    now_utc,
)
from agentmesh.report_html import render_report_html
from agentmesh.routes.deps import current_user, require_default_project
from agentmesh.runtime_admission import current_orchestration_admission
from agentmesh.runtime_capacity import RuntimeCapacityError
from agentmesh.skill_runtime.plan_validation import PlanValidationError, adjust_plan, validate_draft
from agentmesh.skill_runtime.quiesce import OrchestrationQuiescingError
from agentmesh.skill_runtime.recommendation import revalidate_candidate_snapshot
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.skill_runtime.trust import runtime_profile_trust_verifier
from agentmesh.skill_runtime.universal_execution import (
    universal_standard_execution_allowed,
)
from agentmesh.skill_runtime.universal_plan import (
    materialize_universal_draft,
    scenario_assignment_options,
    validate_universal_plan,
)
from agentmesh.store import DeepSearchRequirementConflict, ResearchStoreConflict, store
from agentmesh.task_routing.catalog import (
    TaskCatalogLoadError,
    TaskCatalogV2,
    load_default_task_catalog,
    load_task_catalog_by_identity,
    load_universal_task_catalog,
)

router = APIRouter(prefix="/api/agent/runs", tags=["agent-runs"])
_TERMINAL = {"completed", "partial", "failed", "rejected", "cancelled"}
_RESEARCH_V2_READ_ONLY = "Research-v2 runs are historical and read-only"
_RESEARCH_V3_RETIRED = "Research-v3 is retired and its runs cannot be changed"
_REPORT_READY_STATUSES = {AgentRunStatus.COMPLETED, AgentRunStatus.PARTIAL}
_report_artifact_reader = V1ArtifactReader(store)


class _SSECapacity:
    def __init__(self, *, global_limit: int = 10, user_limit: int = 2, run_limit: int = 1):
        self._global_limit = global_limit
        self._user_limit = user_limit
        self._run_limit = run_limit
        self._lock = threading.Lock()
        self._active = 0
        self._by_user: dict[str, int] = {}
        self._by_run: dict[str, int] = {}

    def acquire(self, *, user_id: str, run_id: str) -> bool:
        with self._lock:
            if (
                self._active >= self._global_limit
                or self._by_user.get(user_id, 0) >= self._user_limit
                or self._by_run.get(run_id, 0) >= self._run_limit
            ):
                return False
            self._active += 1
            self._by_user[user_id] = self._by_user.get(user_id, 0) + 1
            self._by_run[run_id] = self._by_run.get(run_id, 0) + 1
            return True

    def release(self, *, user_id: str, run_id: str) -> None:
        with self._lock:
            if self._by_run.get(run_id, 0) <= 0:
                return
            self._active -= 1
            self._by_user[user_id] -= 1
            self._by_run[run_id] -= 1
            if self._by_user[user_id] == 0:
                del self._by_user[user_id]
            if self._by_run[run_id] == 0:
                del self._by_run[run_id]


_sse_capacity = _SSECapacity()


def _public_agent_run_event(event: AgentRunEvent) -> AgentRunEvent:
    if event.event_type == "tool_call_claimed":
        claim = RuntimeToolCallClaimV1.model_validate(event.payload)
        payload: dict[str, object] = {
            "schema_version": claim.schema_version,
            "call_id": claim.call_id,
            "tool_name": claim.tool_name,
            "side_effect": claim.side_effect,
            "claimed_at": claim.claimed_at.isoformat(),
        }
        return event.model_copy(update={"payload": payload})
    if event.event_type in {
        "tool_call_settled",
        "tool_call_abandoned",
        "tool_call_outcome_unknown",
    }:
        outcome = RuntimeToolCallOutcomeV1.model_validate(event.payload)
        return event.model_copy(
            update={
                "payload": {
                    "schema_version": outcome.schema_version,
                    "call_id": outcome.call_id,
                    "outcome": outcome.outcome,
                    "error_code": outcome.error_code,
                    "recorded_at": outcome.recorded_at.isoformat(),
                }
            }
        )
    return event


def _require_planned_mutation_enabled(run: AgentRun) -> None:
    if skill_orchestration_mode() is not SkillOrchestrationMode.OFF:
        return
    if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
        raise _deepsearch_admission_error("execution_unavailable", status_code=409)
    raise HTTPException(
        status_code=409,
        detail={"code": "skill_orchestration_disabled"},
    )


def _visible_run(run_id: str, user: User):
    run = store.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if (
        run.user_id != user.id
        or run.workspace_id != user.workspace_id
        or not store.user_can_execute_agent_run(user.id, run.id)
    ):
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.planning_mode == AgentPlanningMode.DEEPSEARCH:
        thread = store.get_chat_thread(run.thread_id)
        if (
            thread is None
            or thread.status != "active"
            or thread.user_id != run.user_id
            or thread.workspace_id != run.workspace_id
            or thread.project_id != run.project_id
        ):
            raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def _visible_plan(run_id: str, user: User):
    run = _visible_run(run_id, user)
    plan = store.get_skill_plan_for_run(run.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Skill plan not found")
    return run, plan


def _report_unavailable() -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "report_unavailable"})


def _deepsearch_report_source(run, plan, user: User) -> tuple[str, str, str | None]:  # noqa: ANN001
    artifact_id = plan.report_artifact_id
    if artifact_id is None or plan.report_content_hash is None:
        raise _report_unavailable()
    try:
        artifact = _report_artifact_reader.read_for_owner(
            artifact_id,
            reader_scope=ArtifactAccessScope(user_id=user.id, workspace_id=user.workspace_id),
        )
        parsed = DeepSearchArtifactSchemaRegistry.parse(
            artifact.artifact_type,
            artifact.schema_version or "",
            artifact.content,
        )
    except ArtifactAccessError as error:
        status_code = 404 if error.code == "artifact_not_found" else 409
        raise HTTPException(status_code=status_code, detail={"code": error.code}) from error
    if (
        not isinstance(parsed, DeepSearchReportV1)
        or artifact.verification_state is not ArtifactVerificationState.SEALED
        or artifact.content_type != "application/json"
        or artifact.content_hash != plan.report_content_hash
        or parsed.run_id != run.id
        or parsed.plan_id != plan.id
        or run.output_text != parsed.rendered_text
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "artifact_integrity_failed"},
        )
    return parsed.title, parsed.rendered_text, artifact.content_hash


def _standard_report_source(run, plan) -> tuple[str, str, None]:  # noqa: ANN001
    if plan.synthesis is None or not run.output_text.strip():
        raise _report_unavailable()
    try:
        SkillSynthesisResult.model_validate(plan.synthesis)
    except ValueError as error:
        raise HTTPException(status_code=409, detail={"code": "report_integrity_failed"}) from error
    input_title = " ".join(run.input_text.split())
    title = f"{input_title[:72]} · 报告" if input_title else "AgentMesh 报告"
    return title, run.output_text, None


def _report_source(run_id: str, user: User) -> tuple[AgentRun, str, str, str | None]:
    run, plan = _visible_plan(run_id, user)
    if (
        run.orchestration_version != "v1"
        or run.status not in _REPORT_READY_STATUSES
    ):
        raise _report_unavailable()
    if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
        title, markdown, content_hash = _deepsearch_report_source(run, plan, user)
    else:
        title, markdown, content_hash = _standard_report_source(run, plan)
    return run, title, markdown, content_hash


def _report_filename(run_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip("-.")[:64]
    return f"agentmesh-report-{safe_id or 'report'}.html"


def _reject_expired_plan_approval(run, user: User) -> None:  # noqa: ANN001
    if (
        run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
        and run.deadline_at is not None
        and now_utc() >= run.deadline_at
    ):
        store.cancel_agent_run_tree(run.id, user_id=user.id)
        raise HTTPException(status_code=409, detail="Skill plan approval deadline expired")


def _expire_deepsearch_mutation(run, user: User):  # noqa: ANN001, ANN201
    if run.planning_mode != AgentPlanningMode.DEEPSEARCH:
        return run
    refreshed = store.expire_deepsearch_run_if_needed(run.id, user_id=user.id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if refreshed.status == AgentRunStatus.CANCELLED and refreshed.error_code in {
        "deepsearch_interaction_expired",
        "deepsearch_run_expired",
    }:
        raise HTTPException(status_code=409, detail={"code": refreshed.error_code})
    return refreshed


def _universal_catalog_for_plan(plan) -> TaskCatalogV2:  # noqa: ANN001
    if plan.routing_result is None:
        return load_universal_task_catalog()
    try:
        resolved = load_task_catalog_by_identity(
            plan.routing_result.catalog_version,
            plan.routing_result.catalog_hash,
        )
    except TaskCatalogLoadError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "task_catalog_snapshot_unavailable"},
        ) from error
    if not isinstance(resolved, TaskCatalogV2):
        raise HTTPException(
            status_code=409,
            detail={"code": "task_catalog_snapshot_unavailable"},
        )
    return resolved


def _current_plan_candidates(
    plan,
    user: User,
    *,
    require_concrete_assignments: bool = False,
    dynamic_skill_ids: set[str] | None = None,
):  # noqa: ANN001, ANN201
    if plan.candidate_snapshot is not None:
        task_catalog = _universal_catalog_for_plan(plan)
        try:
            from agentmesh.routes.chat import agent

            runtime = agent.agent_runtime
            profile_trust = getattr(runtime, "profile_trust", None) or runtime_profile_trust_verifier()
            candidates = revalidate_candidate_snapshot(
                snapshot=plan.candidate_snapshot,
                repository=store,
                catalog=catalog_service(),
                user=user,
                intent=plan.intent,
                profile_trust=profile_trust,
                dynamic_skill_ids=dynamic_skill_ids,
            )
            validate_universal_plan(
                plan=plan,
                candidates=candidates,
                catalog=task_catalog,
                require_concrete_assignments=require_concrete_assignments,
            )
            return candidates
        except (PlanValidationError, ValueError) as error:
            code = error.codes if isinstance(error, PlanValidationError) else [str(error)]
            raise HTTPException(status_code=409, detail={"codes": code}) from error

    retriever = SkillCandidateRetriever(store, catalog_service())
    if plan.routing_result is None:
        candidates, _diagnostics = retriever.recommend(user, plan.intent)
    else:
        task_catalog = load_default_task_catalog()
        if plan.routing_result.catalog_hash != task_catalog.manifest.catalog_hash:
            raise HTTPException(status_code=409, detail="The Task Catalog changed after Plan creation")
        candidates, _diagnostics = retriever.recommend_for_route(
            user,
            plan.intent,
            plan.routing_result,
            task_catalog,
        )
    by_id = {candidate.skill_id: candidate for candidate in candidates}
    selected = [by_id[skill_id] for skill_id in plan.candidate_skill_ids if skill_id in by_id]
    if any(node.skill_id not in by_id for node in plan.nodes):
        raise HTTPException(status_code=409, detail="A planned Skill is no longer ready or authorized")
    return selected


def _scenario_assignments_for_update(
    plan,
    request: SkillPlanUpdateRequest,
) -> dict[str, str | None]:  # noqa: ANN001
    selected_skill_ids = set(request.selected_skill_ids)
    assignments = {
        node.skill_id: node.scenario_id
        for node in plan.nodes
        if node.skill_id in selected_skill_ids and node.scenario_id is not None
    }
    assignments.update(request.scenario_assignments)
    return assignments


def _blocked_matches_view(run_id: str) -> list[BlockedSkillMatchPublicV1]:
    for event in reversed(store.list_agent_run_events(run_id)):
        if event.event_type != "skill_search_completed":
            continue
        payload = event.payload.get("blocked_matches")
        if not isinstance(payload, list):
            return []
        try:
            return [
                BlockedSkillMatchPublicV1.model_validate(item)
                for item in payload[:5]
            ]
        except (TypeError, ValueError):
            return []
    return []


def _scenario_assignment_options_view(plan) -> dict[str, list[ScenarioAssignmentOptionV1]]:  # noqa: ANN001
    if plan.candidate_snapshot is None or plan.routing_result is None:
        return {}
    catalog = _universal_catalog_for_plan(plan)
    result: dict[str, list[ScenarioAssignmentOptionV1]] = {}
    for node in plan.nodes:
        options = scenario_assignment_options(
            node=node,
            routing=plan.routing_result,
            catalog=catalog,
        )
        if len(options) <= 1:
            continue
        node_outputs = set(node.output_contract)
        result[node.skill_id] = []
        for scenario_id in options:
            scenario = catalog.get_scenario(scenario_id)
            assert scenario is not None
            matched_outputs = [
                output
                for output in scenario.outputs
                if node_outputs.intersection(output.compatible_output_kinds)
            ]
            result[node.skill_id].append(
                ScenarioAssignmentOptionV1(
                    scenario_id=scenario.id,
                    title=scenario.title,
                    output_ids=tuple(output.id for output in matched_outputs),
                    output_labels=tuple(output.label for output in matched_outputs),
                )
            )
    return result


def _thread(request: AgentRunCreateRequest, user: User) -> ChatThread:
    require_default_project(user, store)
    thread_id = _requested_thread_id(request, user)
    if request.thread_id is not None:
        thread = store.get_chat_thread(thread_id)
        if (
            thread is None
            or thread.status != "active"
            or thread.user_id != user.id
            or thread.workspace_id != user.workspace_id
            or thread.project_id != user.default_project_id
        ):
            raise HTTPException(status_code=404, detail="Chat thread not found")
        return thread
    existing = store.get_chat_thread(thread_id)
    if existing is not None:
        if (
            existing.user_id != user.id
            or existing.workspace_id != user.workspace_id
            or existing.project_id != user.default_project_id
        ):
            raise HTTPException(status_code=409, detail="client_turn_id thread identity conflict")
        return existing
    return store.add_chat_thread(
        ChatThread(
            id=thread_id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            user_id=user.id,
            title=request.content.strip()[:60] or "新的 Agent 运行",
        )
    )


def _requested_thread_id(request: AgentRunCreateRequest, user: User) -> str:
    if request.thread_id is not None:
        return request.thread_id
    return "thread_" + hashlib.sha256(
        f"agent-run-thread-v1\0{user.id}\0{request.client_turn_id}".encode()
    ).hexdigest()[:24]


def _deepsearch_error(reason: str, *, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": f"deepsearch_{reason}"})


def _deepsearch_admission_error(reason: str, *, status_code: int) -> HTTPException:
    record_deepsearch_admission_rejection(reason)
    return _deepsearch_error(reason, status_code=status_code)


def _deepsearch_plan_store_error(error: ResearchStoreConflict) -> HTTPException:
    if isinstance(error, DeepSearchRequirementConflict):
        detail: dict[str, object] = {"code": error.code}
        if error.current_requirement_version is not None:
            detail["current_requirement_version"] = error.current_requirement_version
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=409, detail={"code": "deepsearch_plan_state_conflict"})


def _require_deepsearch_tool_runtime(plan, runtime) -> None:  # noqa: ANN001
    gateway = getattr(getattr(runtime, "tool_factory", None), "gateway", None)
    describe = getattr(gateway, "describe", None)
    unavailable: list[str] = []
    for tool_name in sorted({name for node in plan.nodes for name in node.required_tool_names}):
        try:
            descriptor = describe(tool_name) if callable(describe) else None
        except Exception:  # pragma: no cover - provider adapters must fail closed
            descriptor = None
        if (
            descriptor is None
            or descriptor.execution_mode != "real"
            or descriptor.health_state != "healthy"
        ):
            unavailable.append(tool_name)
    if unavailable:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "deepsearch_tool_runtime_unavailable",
                "tools": unavailable,
            },
        )


def _agent_run_creation_error(error: RuntimeError) -> HTTPException:
    if isinstance(error, OrchestrationQuiescingError):
        return HTTPException(status_code=503, detail={"code": error.code})
    if isinstance(error, RuntimeCapacityError):
        return HTTPException(
            status_code=429,
            detail={"code": error.code, "scope": error.scope},
            headers={"Retry-After": "1"},
        )
    if str(error) == "client_turn_id was already used for another Agent run":
        return HTTPException(status_code=409, detail={"code": "client_turn_id_conflict"})
    return HTTPException(status_code=409, detail=str(error))


@router.post("", response_model=ItemResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_agent_run(
    request: AgentRunCreateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    from agentmesh.routes.chat import agent

    skill_name = (request.skill_name or "").removeprefix("$").strip() or None
    explicit_name = (request.explicit_skill_name or "").removeprefix("$").strip() or None
    if skill_name and explicit_name and skill_name != explicit_name:
        raise HTTPException(status_code=400, detail="skill_name and explicit_skill_name disagree")
    requested_skill_name = explicit_name or skill_name
    prior = store.get_agent_run_by_client_turn(user.id, request.client_turn_id)
    skill = None
    canonical_skill_name = requested_skill_name
    if requested_skill_name and request.planning_mode == AgentPlanningMode.STANDARD:
        skill = catalog_service().get_by_name(requested_skill_name, user.personal_agent_id)
        if skill is not None:
            canonical_skill_name = skill.name
        elif prior is not None and prior.skill_name == requested_skill_name:
            canonical_skill_name = prior.skill_name
        elif prior is None:
            raise HTTPException(status_code=404, detail="Skill not found")

    thread_id = (
        prior.thread_id
        if prior is not None and prior.create_request_hash is None and request.thread_id is None
        else _requested_thread_id(request, user)
    )
    mode = skill_orchestration_mode()
    if prior is None and request.planning_mode is AgentPlanningMode.DEEPSEARCH:
        if requested_skill_name is not None:
            raise HTTPException(status_code=400, detail={"code": "deepsearch_explicit_skill_conflict"})
        if request.orchestration_mode != SkillOrchestrationRequestMode.AUTO:
            raise HTTPException(status_code=400, detail={"code": "deepsearch_requires_auto"})
        if not deepsearch_enabled():
            raise _deepsearch_admission_error("disabled", status_code=409)
        if mode != SkillOrchestrationMode.EXECUTE:
            raise _deepsearch_admission_error("execution_unavailable", status_code=409)
    if prior is None:
        runtime = agent.agent_runtime
        contract_selector = getattr(runtime, "planning_contract_for", None)
        planned_request = request.planning_mode is AgentPlanningMode.DEEPSEARCH or (
            skill is None
            and request.orchestration_mode is SkillOrchestrationRequestMode.AUTO
            and mode is not SkillOrchestrationMode.OFF
        )
        selected_contract = (
            contract_selector(planning_mode=request.planning_mode, planned=planned_request)
            if callable(contract_selector)
            else None
        )
        execution_selector = getattr(runtime, "execution_contract_for", None)
        selected_execution_contract = (
            execution_selector(selected_contract)
            if callable(execution_selector)
            else None
        )
    else:
        selected_contract = prior.planning_contract_version
        selected_execution_contract = prior.execution_contract_version
    create_request_hash = agent_run_create_request_hash(
        user_id=user.id,
        thread_id=thread_id,
        client_turn_id=request.client_turn_id,
        content=request.content,
        skill_name=canonical_skill_name,
        orchestration_mode=request.orchestration_mode,
        planning_mode=request.planning_mode,
        retry_of_run_id=None,
        planning_contract_version=selected_contract,
        execution_contract_version=selected_execution_contract,
    )
    if prior is not None:
        prior = _visible_run(prior.id, user)
        if not agent_run_create_request_matches(
            prior,
            create_request_hash=create_request_hash,
            user_id=user.id,
            client_turn_id=request.client_turn_id,
            thread_id=thread_id,
            content=request.content,
            skill_id=skill.id if skill is not None else prior.skill_id if prior.skill_name == canonical_skill_name else None,
            skill_name=canonical_skill_name,
            orchestration_mode=request.orchestration_mode,
            planning_mode=request.planning_mode,
            retry_of_run_id=None,
            planning_contract_version=prior.planning_contract_version,
            execution_contract_version=prior.execution_contract_version,
        ):
            raise HTTPException(status_code=409, detail={"code": "client_turn_id_conflict"})
        return ItemResponse(item=prior)

    runtime = agent.agent_runtime
    if request.planning_mode == AgentPlanningMode.DEEPSEARCH:
        availability = evaluate_deepsearch_availability(runtime=runtime, user=user)
        if not availability.available:
            reason = availability.reason_code.value if availability.reason_code is not None else "runtime_unavailable"
            status_code = 409 if reason in {"disabled", "execution_unavailable"} else 503
            raise _deepsearch_admission_error(reason, status_code=status_code)
        thread = _thread(request, user)
        starter = runtime.start_deepsearch
        try:
            run = await starter(
                content=request.content,
                user=user,
                thread_id=thread.id,
                history=store.list_thread_messages(thread.id),
                client_turn_id=request.client_turn_id,
                mode=mode,
                create_request_hash=create_request_hash,
            )
        except RuntimeError as error:
            raise _agent_run_creation_error(error) from error
        if run.orchestration_version != "v1" or run.planning_mode != AgentPlanningMode.DEEPSEARCH:
            raise RuntimeError("DeepSearch Runtime returned an invalid Run identity")
        return ItemResponse(item=run)

    if runtime is None or not runtime.enabled:
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    thread = _thread(request, user)
    try:
        if (
            skill is None
            and request.orchestration_mode == "auto"
            and mode != SkillOrchestrationMode.OFF
        ):
            run = await runtime.start_orchestrated(
                content=request.content,
                user=user,
                thread_id=thread.id,
                history=store.list_recent_thread_messages(thread.id),
                client_turn_id=request.client_turn_id,
                mode=mode,
            )
        else:
            run = await runtime.start(
                content=request.content,
                user=user,
                thread_id=thread.id,
                history=store.list_thread_messages(thread.id),
                skill=skill,
                client_turn_id=request.client_turn_id,
                requested_orchestration_mode=request.orchestration_mode,
            )
    except RuntimeError as error:
        raise _agent_run_creation_error(error) from error
    return ItemResponse(item=run)


@router.get("/{run_id}", response_model=ItemResponse)
def get_agent_run(run_id: str, user: User = Depends(current_user)) -> ItemResponse:
    return ItemResponse(item=_visible_run(run_id, user))


@router.get("/{run_id}/report.html", response_class=HTMLResponse)
def get_agent_run_report_html(
    run_id: str,
    download: bool = False,
    user: User = Depends(current_user),
) -> HTMLResponse:
    run, title, markdown, artifact_hash = _report_source(run_id, user)
    encoded_run_id = quote(run.id, safe="")
    back_href = f"/workspace/thread/{quote(run.thread_id, safe='')}?run={encoded_run_id}"
    download_href = f"/api/agent/runs/{encoded_run_id}/report.html?download=true"
    status_label = "完整输出" if run.status is AgentRunStatus.COMPLETED else "部分完成"
    document = render_report_html(
        title=title,
        markdown=markdown,
        status_label=status_label,
        back_href=None if download else back_href,
        download_href=None if download else download_href,
    )
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; img-src https: http: data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if artifact_hash is not None:
        headers["X-AgentMesh-Artifact-Hash"] = artifact_hash
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{_report_filename(run.id)}"'
    return HTMLResponse(content=document, headers=headers)


@router.get(
    "/{run_id}/plan",
    response_model=DeepSearchPlanDetailResponse | SkillPlanDetailResponse,
)
def get_agent_run_plan(
    run_id: str,
    user: User = Depends(current_user),
) -> DeepSearchPlanDetailResponse | SkillPlanDetailResponse:
    run, plan = _visible_plan(run_id, user)
    results = store.list_skill_node_results(plan.id)
    if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
        return DeepSearchPlanDetailResponse(
            plan=DeepSearchPlanViewV1.from_plan(plan),
            results=results,
            synthesis=None,
            scenario_assignment_options=_scenario_assignment_options_view(plan),
            blocked_matches=_blocked_matches_view(run.id),
        )
    return SkillPlanDetailResponse(
        plan=SkillPlanPublicView.from_plan(plan),
        results=results,
        synthesis=SkillSynthesisResult.model_validate(plan.synthesis) if plan.synthesis is not None else None,
        scenario_assignment_options=_scenario_assignment_options_view(plan),
        blocked_matches=_blocked_matches_view(run.id),
    )


@router.patch(
    "/{run_id}/plan",
    response_model=DeepSearchPlanDetailResponse | SkillPlanDetailResponse,
)
def update_agent_run_plan(
    run_id: str,
    request: SkillPlanUpdateRequest,
    user: User = Depends(current_user),
) -> DeepSearchPlanDetailResponse | SkillPlanDetailResponse:
    run, plan = _visible_plan(run_id, user)
    run = _expire_deepsearch_mutation(run, user)
    _reject_expired_plan_approval(run, user)
    _require_planned_mutation_enabled(run)
    if run.status != AgentRunStatus.WAITING_PLAN_APPROVAL or plan.status != SkillPlanStatus.WAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Skill plan is not editable")
    if plan.version != request.expected_version:
        raise HTTPException(status_code=409, detail="Skill plan version conflict")
    if request.scenario_assignments and plan.candidate_snapshot is None:
        raise HTTPException(
            status_code=400,
            detail={"codes": ["scenario_assignment_not_supported"]},
        )
    try:
        candidates = _current_plan_candidates(
            plan,
            user,
            dynamic_skill_ids=set(request.selected_skill_ids),
        )
        adjusted = adjust_plan(plan, request, candidates)
        if plan.candidate_snapshot is not None:
            assignments = _scenario_assignments_for_update(plan, request)
            materialized = materialize_universal_draft(
                draft=SkillPlanDraft(
                    output_contract=adjusted.output_contract,
                    synthesis_output_contract=adjusted.synthesis_output_contract,
                    capability_gaps=adjusted.capability_gaps,
                    nodes=adjusted.nodes,
                ),
                intent=plan.intent,
                candidates=candidates,
                snapshot=plan.candidate_snapshot,
                routing=plan.routing_result,
                catalog=_universal_catalog_for_plan(plan),
                skill_lookup=store.get_skill_definition,
                scenario_assignments=assignments,
            )
            adjusted.nodes = materialized.nodes
            adjusted.capability_gaps = materialized.capability_gaps
            adjusted.synthesis_output_contract = materialized.synthesis_output_contract
            validate_universal_plan(
                plan=adjusted,
                candidates=candidates,
                catalog=_universal_catalog_for_plan(plan),
                require_concrete_assignments=False,
            )
        elif run.planning_mode is AgentPlanningMode.DEEPSEARCH:
            adjusted = freeze_deepsearch_plan_resources(
                plan=adjusted,
                candidates=candidates,
                skill_definition_lookup=store.get_skill_definition,
            )
    except (PlanValidationError, ValueError) as error:
        codes = error.codes if isinstance(error, PlanValidationError) else [str(error)]
        raise HTTPException(status_code=400, detail={"codes": codes}) from error
    if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
        adjusted.version = request.expected_version + 1
        try:
            adjusted.plan_content_hash = plan_content_hash(adjusted)
            checked_at = now_utc()
            snapshot = build_deepsearch_plan_snapshot(
                run=run,
                plan=adjusted,
                created_at=checked_at,
            )
            with current_orchestration_admission().permit():
                transition = store.update_deepsearch_plan_and_snapshot(
                    run_id=run.id,
                    user_id=user.id,
                    expected_plan_version=request.expected_version,
                    plan=adjusted,
                    plan_snapshot=snapshot,
                    checked_at=checked_at,
                )
        except ResearchStoreConflict as error:
            raise _deepsearch_plan_store_error(error) from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "deepsearch_plan_integrity_failed"},
            ) from error
        if transition is None:
            raise HTTPException(status_code=409, detail="Skill plan version conflict")
        transitioned_plan, _transitioned_run, _snapshot = transition
        return DeepSearchPlanDetailResponse(
            plan=DeepSearchPlanViewV1.from_plan(transitioned_plan),
            results=[],
            synthesis=None,
            scenario_assignment_options=_scenario_assignment_options_view(
                transitioned_plan
            ),
            blocked_matches=_blocked_matches_view(run.id),
        )
    with current_orchestration_admission().permit():
        updated = store.compare_and_swap_skill_plan(
            adjusted,
            expected_version=request.expected_version,
            events=[
                (
                    "plan_updated",
                    {
                        "plan_id": adjusted.id,
                        "version": request.expected_version + 1,
                        "selected_skill_ids": request.selected_skill_ids,
                    },
                )
            ],
        )
    if not updated:
        raise HTTPException(status_code=409, detail="Skill plan version conflict")
    return SkillPlanDetailResponse(
        plan=SkillPlanPublicView.from_plan(adjusted),
        results=[],
        synthesis=None,
        scenario_assignment_options=_scenario_assignment_options_view(adjusted),
        blocked_matches=_blocked_matches_view(run.id),
    )


@router.post(
    "/{run_id}/plan/approve",
    response_model=DeepSearchPlanTransitionResponse | SkillPlanTransitionResponse,
)
async def approve_agent_run_plan(
    run_id: str,
    request: SkillPlanVersionRequest,
    user: User = Depends(current_user),
) -> DeepSearchPlanTransitionResponse | SkillPlanTransitionResponse:
    from agentmesh.routes.chat import agent

    run, plan = _visible_plan(run_id, user)
    run = _expire_deepsearch_mutation(run, user)
    _reject_expired_plan_approval(run, user)
    _require_planned_mutation_enabled(run)
    configured_mode = skill_orchestration_mode()
    deepsearch = run.planning_mode is AgentPlanningMode.DEEPSEARCH
    if (
        run.planning_contract_version
        is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
        and not universal_standard_execution_allowed(
            run_contract=run.execution_contract_version,
            plan_contract=plan.execution_contract_version,
        )
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "universal_execution_not_available"},
        )
    if deepsearch and (
        configured_mode != SkillOrchestrationMode.EXECUTE
        or run.orchestration_mode != SkillOrchestrationMode.EXECUTE.value
    ):
        raise _deepsearch_error("execution_unavailable", status_code=409)
    if not deepsearch and configured_mode == SkillOrchestrationMode.OFF:
        store.cancel_agent_run_tree(run.id, user_id=user.id)
        raise HTTPException(status_code=409, detail="Skill orchestration is disabled")
    candidates = (
        _current_plan_candidates(
            plan,
            user,
            require_concrete_assignments=True,
            dynamic_skill_ids={node.skill_id for node in plan.nodes},
        )
        if plan.candidate_snapshot is not None
        else _current_plan_candidates(plan, user)
    )
    try:
        validate_draft(
            SkillPlanDraft(
                output_contract=plan.output_contract,
                synthesis_output_contract=plan.synthesis_output_contract,
                capability_gaps=plan.capability_gaps,
                nodes=plan.nodes,
            ),
            candidates,
            intent=plan.intent,
            universal=plan.candidate_snapshot is not None,
        )
    except PlanValidationError as error:
        raise HTTPException(status_code=409, detail={"codes": error.codes}) from error
    runtime = agent.agent_runtime
    if deepsearch:
        if runtime is None or not runtime.enabled:
            raise _deepsearch_error("execution_unavailable", status_code=409)
        _require_deepsearch_tool_runtime(plan, runtime)
        if not store.user_can_execute_agent_run(
            user.id,
            run.id,
            allowed_statuses={AgentRunStatus.WAITING_PLAN_APPROVAL},
        ):
            raise HTTPException(status_code=404, detail="Agent run not found")
        approved = plan.model_copy(
            deep=True,
            update={
                "version": request.expected_version + 1,
                "status": SkillPlanStatus.APPROVED,
            },
        )
        try:
            approved_hash = plan_content_hash(approved)
            if approved_hash != plan.plan_content_hash:
                raise ValueError("DeepSearch Plan content changed during approval")
            approved.plan_content_hash = approved_hash
            checked_at = now_utc()
            snapshot = build_deepsearch_plan_snapshot(
                run=run,
                plan=approved,
                created_at=checked_at,
            )
            approved.approved_plan_artifact_id = snapshot.id
            dispatch_factory = getattr(runtime, "new_dispatch_receipt", None)
            dispatch_receipt = (
                dispatch_factory(run.id, "approved_plan")
                if callable(dispatch_factory)
                else None
            )
            with current_orchestration_admission().permit():
                transition = store.approve_deepsearch_plan_and_transition(
                    run_id=run.id,
                    user_id=user.id,
                    expected_plan_version=request.expected_version,
                    plan=approved,
                    plan_snapshot=snapshot,
                    checked_at=checked_at,
                    dispatch=dispatch_receipt,
                )
        except ResearchStoreConflict as error:
            raise _deepsearch_plan_store_error(error) from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "deepsearch_plan_integrity_failed"},
            ) from error
        if transition is None:
            raise HTTPException(status_code=409, detail="Skill plan approval conflict")
        transitioned_plan, transitioned_run, _snapshot = transition
        try:
            if dispatch_receipt is None:
                await runtime.start_approved_skill_plan(transitioned_plan.id, user=user)
            else:
                await runtime.start_approved_skill_plan(
                    transitioned_plan.id,
                    user=user,
                    dispatch_receipt=dispatch_receipt,
                )
        except (LookupError, PermissionError) as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "deepsearch_plan_state_conflict"},
            ) from error
        except OrchestrationQuiescingError as error:
            raise HTTPException(status_code=503, detail={"code": error.code}) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503,
                detail={"code": "deepsearch_runtime_unavailable"},
            ) from error
        return DeepSearchPlanTransitionResponse(
            plan=DeepSearchPlanViewV1.from_plan(transitioned_plan),
            run=transitioned_run,
        )
    requested_mode = SkillOrchestrationMode(run.orchestration_mode)
    if requested_mode == SkillOrchestrationMode.PREVIEW or configured_mode == SkillOrchestrationMode.PREVIEW:
        message = "计划已确认；当前为 preview 模式，未执行任何 Skill。"
        with current_orchestration_admission().permit():
            transition = store.transition_skill_plan_and_run(
                plan_id=plan.id,
                run_id=run.id,
                expected_version=request.expected_version,
                expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
                expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
                next_plan_status=SkillPlanStatus.APPROVED,
                next_run_status=AgentRunStatus.COMPLETED,
                events=[
                    ("plan_approved", {"plan_id": plan.id}),
                    ("run_completed", {"preview_only": True}),
                ],
                output_text=message,
            )
        if transition is None:
            raise HTTPException(status_code=409, detail="Skill plan approval conflict")
        transitioned_plan, transitioned_run = transition
        if agent.agent_runtime is not None:
            agent.agent_runtime.project_orchestration_output(transitioned_run, message)
        return SkillPlanTransitionResponse(
            plan=SkillPlanPublicView.from_plan(transitioned_plan),
            run=transitioned_run,
            scenario_assignment_options=_scenario_assignment_options_view(transitioned_plan),
        )
    if runtime is None or not runtime.enabled:
        store.cancel_agent_run_tree(run.id, user_id=user.id)
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    if not store.user_can_execute_agent_run(
        user.id,
        run.id,
        allowed_statuses={AgentRunStatus.WAITING_PLAN_APPROVAL},
    ):
        raise HTTPException(status_code=404, detail="Agent run not found")
    dispatch_factory = getattr(runtime, "new_dispatch_receipt", None)
    dispatch_receipt = (
        dispatch_factory(run.id, "approved_plan")
        if callable(dispatch_factory)
        else None
    )
    with current_orchestration_admission().permit():
        transition = store.transition_skill_plan_and_run(
            plan_id=plan.id,
            run_id=run.id,
            expected_version=request.expected_version,
            expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
            expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            next_plan_status=SkillPlanStatus.APPROVED,
            next_run_status=AgentRunStatus.RUNNING,
            events=[("plan_approved", {"plan_id": plan.id})],
            dispatch=dispatch_receipt,
        )
    if transition is None:
        raise HTTPException(status_code=409, detail="Skill plan approval conflict")
    transitioned_plan, transitioned_run = transition
    try:
        if dispatch_receipt is None:
            await runtime.start_approved_skill_plan(transitioned_plan.id, user=user)
        else:
            await runtime.start_approved_skill_plan(
                transitioned_plan.id,
                user=user,
                dispatch_receipt=dispatch_receipt,
            )
    except OrchestrationQuiescingError as error:
        raise HTTPException(status_code=503, detail={"code": error.code}) from error
    except (LookupError, PermissionError, RuntimeError) as error:
        store.cancel_agent_run_tree(transitioned_run.id, user_id=user.id)
        status_code = 404 if isinstance(error, (LookupError, PermissionError)) else 409
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    return SkillPlanTransitionResponse(
        plan=SkillPlanPublicView.from_plan(transitioned_plan),
        run=transitioned_run,
        scenario_assignment_options=_scenario_assignment_options_view(transitioned_plan),
    )


@router.post(
    "/{run_id}/plan/reject",
    response_model=DeepSearchPlanTransitionResponse | SkillPlanTransitionResponse,
)
def reject_agent_run_plan(
    run_id: str,
    request: SkillPlanVersionRequest,
    user: User = Depends(current_user),
) -> DeepSearchPlanTransitionResponse | SkillPlanTransitionResponse:
    from agentmesh.routes.chat import agent

    run, plan = _visible_plan(run_id, user)
    run = _expire_deepsearch_mutation(run, user)
    _reject_expired_plan_approval(run, user)
    _require_planned_mutation_enabled(run)
    message = "你已拒绝该多 Skill 计划，未执行任何节点。"
    with current_orchestration_admission().permit():
        transition = store.transition_skill_plan_and_run(
            plan_id=plan.id,
            run_id=run.id,
            expected_version=request.expected_version,
            expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
            expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            next_plan_status=SkillPlanStatus.REJECTED,
            next_run_status=AgentRunStatus.REJECTED,
            events=[("plan_rejected", {"plan_id": plan.id}), ("run_rejected", {})],
            output_text=message,
        )
    if transition is None:
        raise HTTPException(status_code=409, detail="Skill plan rejection conflict")
    transitioned_plan, transitioned_run = transition
    if agent.agent_runtime is not None:
        agent.agent_runtime.project_orchestration_output(transitioned_run, message)
    if transitioned_run.planning_mode is AgentPlanningMode.DEEPSEARCH:
        return DeepSearchPlanTransitionResponse(
            plan=DeepSearchPlanViewV1.from_plan(transitioned_plan),
            run=transitioned_run,
        )
    return SkillPlanTransitionResponse(
        plan=SkillPlanPublicView.from_plan(transitioned_plan),
        run=transitioned_run,
        scenario_assignment_options=_scenario_assignment_options_view(transitioned_plan),
    )


@router.post("/{run_id}/retry", response_model=ItemResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_agent_run(
    run_id: str,
    request: AgentRunRetryRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    from agentmesh.routes.chat import agent

    prior = _visible_run(run_id, user)
    if prior.orchestration_version == "research-v2":
        raise HTTPException(status_code=409, detail=_RESEARCH_V2_READ_ONLY)
    if prior.orchestration_version == "research-v3":
        raise HTTPException(status_code=409, detail=_RESEARCH_V3_RETIRED)
    retry_mode = prior.requested_orchestration_mode
    existing_retry = store.get_agent_run_by_client_turn(user.id, request.client_turn_id)
    if existing_retry is not None:
        retry_create_request_hash = agent_run_create_request_hash(
            user_id=user.id,
            thread_id=prior.thread_id,
            client_turn_id=request.client_turn_id,
            content=prior.input_text,
            skill_name=prior.skill_name,
            orchestration_mode=retry_mode,
            planning_mode=prior.planning_mode,
            retry_of_run_id=prior.id,
            planning_contract_version=existing_retry.planning_contract_version,
            execution_contract_version=existing_retry.execution_contract_version,
        )
        existing_retry = _visible_run(existing_retry.id, user)
        if (
            existing_retry.workspace_id != prior.workspace_id
            or existing_retry.project_id != prior.project_id
            or not agent_run_create_request_matches(
                existing_retry,
                create_request_hash=retry_create_request_hash,
                user_id=user.id,
                client_turn_id=request.client_turn_id,
                thread_id=prior.thread_id,
                content=prior.input_text,
                skill_id=prior.skill_id,
                skill_name=prior.skill_name,
                orchestration_mode=retry_mode,
                planning_mode=prior.planning_mode,
                retry_of_run_id=prior.id,
                planning_contract_version=existing_retry.planning_contract_version,
                execution_contract_version=existing_retry.execution_contract_version,
            )
        ):
            raise HTTPException(status_code=409, detail={"code": "client_turn_id_conflict"})
        return ItemResponse(item=existing_retry)
    retry_block_reason = store.runtime_tool_retry_block_reason(prior.id)
    if retry_block_reason is not None:
        raise HTTPException(status_code=409, detail={"code": retry_block_reason})
    if prior.planning_mode == AgentPlanningMode.DEEPSEARCH:
        prior = _expire_deepsearch_mutation(prior, user)
        disposition = deepsearch_retry_disposition(prior)
        if disposition == DeepSearchRetryDisposition.REVISE_GOAL:
            raise HTTPException(status_code=409, detail={"code": "deepsearch_goal_revision_required"})
        if disposition != DeepSearchRetryDisposition.RETRY_RUN:
            raise HTTPException(status_code=409, detail={"code": "deepsearch_retry_not_allowed"})
    if prior.status not in {
        AgentRunStatus.PARTIAL,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.REJECTED,
    }:
        raise HTTPException(status_code=409, detail="Only terminal unsuccessful Agent runs can be retried")
    runtime = agent.agent_runtime
    contract_selector = getattr(runtime, "planning_contract_for", None)
    selected_contract = (
        contract_selector(planning_mode=prior.planning_mode, planned=True)
        if callable(contract_selector)
        else None
    )
    execution_selector = getattr(runtime, "execution_contract_for", None)
    selected_execution_contract = (
        execution_selector(selected_contract)
        if callable(execution_selector)
        else None
    )
    retry_create_request_hash = agent_run_create_request_hash(
        user_id=user.id,
        thread_id=prior.thread_id,
        client_turn_id=request.client_turn_id,
        content=prior.input_text,
        skill_name=prior.skill_name,
        orchestration_mode=retry_mode,
        planning_mode=prior.planning_mode,
        retry_of_run_id=prior.id,
        planning_contract_version=selected_contract,
        execution_contract_version=selected_execution_contract,
    )
    if prior.planning_mode == AgentPlanningMode.DEEPSEARCH:
        if not deepsearch_enabled():
            raise _deepsearch_admission_error("disabled", status_code=409)
        mode = skill_orchestration_mode()
        if mode != SkillOrchestrationMode.EXECUTE:
            raise _deepsearch_admission_error("execution_unavailable", status_code=409)
        availability = evaluate_deepsearch_availability(runtime=runtime, user=user)
        if not availability.available:
            reason = availability.reason_code.value if availability.reason_code is not None else "runtime_unavailable"
            status_code = 409 if reason in {"disabled", "execution_unavailable"} else 503
            raise _deepsearch_admission_error(reason, status_code=status_code)
        try:
            retried = await runtime.start_deepsearch(
                content=prior.input_text,
                user=user,
                thread_id=prior.thread_id,
                history=store.list_thread_messages(prior.thread_id),
                client_turn_id=request.client_turn_id,
                mode=mode,
                project_id=prior.project_id,
                retry_of_run_id=prior.id,
                create_request_hash=retry_create_request_hash,
            )
        except RuntimeError as error:
            raise _agent_run_creation_error(error) from error
        if (
            retried.orchestration_version != "v1"
            or retried.planning_mode != AgentPlanningMode.DEEPSEARCH
            or retried.retry_of_run_id != prior.id
            or retried.project_id != prior.project_id
        ):
            raise RuntimeError("DeepSearch Runtime returned an invalid retry identity")
        return ItemResponse(item=retried)
    if runtime is None or not runtime.enabled:
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    try:
        if prior.plan_id:
            mode = skill_orchestration_mode()
            if mode == SkillOrchestrationMode.OFF:
                raise HTTPException(status_code=409, detail="Skill orchestration is disabled")
            prior_plan = store.get_skill_plan_for_run(prior.id)
            if prior_plan is None:
                raise HTTPException(status_code=409, detail="Prior Skill plan is missing")
            retried = await runtime.retry_orchestrated(
                prior_run=prior,
                prior_plan=prior_plan,
                user=user,
                client_turn_id=request.client_turn_id,
                mode=mode,
                history=store.list_recent_thread_messages(prior.thread_id),
            )
        else:
            if prior.requested_orchestration_mode == SkillOrchestrationRequestMode.AUTO:
                mode = skill_orchestration_mode()
                if mode == SkillOrchestrationMode.OFF:
                    raise HTTPException(status_code=409, detail="Skill orchestration is disabled")
                retried = await runtime.start_orchestrated(
                    content=prior.input_text,
                    user=user,
                    thread_id=prior.thread_id,
                    history=store.list_recent_thread_messages(prior.thread_id),
                    client_turn_id=request.client_turn_id,
                    mode=mode,
                    project_id=prior.project_id,
                    retry_of_run_id=prior.id,
                )
            else:
                skill = (
                    catalog_service().get_by_name(prior.skill_name or "", user.personal_agent_id)
                    if prior.skill_name
                    else None
                )
                if prior.skill_name and skill is None:
                    raise HTTPException(status_code=409, detail="The original Skill is no longer ready or authorized")
                retried = await runtime.start(
                    content=prior.input_text,
                    user=user,
                    thread_id=prior.thread_id,
                    history=store.list_thread_messages(prior.thread_id),
                    skill=skill,
                    client_turn_id=request.client_turn_id,
                    project_id=prior.project_id,
                    requested_orchestration_mode=prior.requested_orchestration_mode,
                    retry_of_run_id=prior.id,
                )
    except PlanValidationError as error:
        raise HTTPException(status_code=409, detail={"codes": error.codes}) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ItemResponse(item=retried)


@router.get("/{run_id}/events", response_model=AgentRunEventsResponse)
def get_agent_run_events(
    run_id: str,
    after_sequence: int = 0,
    user: User = Depends(current_user),
) -> AgentRunEventsResponse:
    _visible_run(run_id, user)
    events = store.list_agent_run_events(run_id, after_sequence=max(0, after_sequence))
    return AgentRunEventsResponse(items=[_public_agent_run_event(event) for event in events])


@router.get("/{run_id}/events/stream")
def stream_agent_run_events(
    run_id: str,
    after_sequence: int = 0,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: User = Depends(current_user),
) -> StreamingResponse:
    _visible_run(run_id, user)
    if not _sse_capacity.acquire(user_id=user.id, run_id=run_id):
        raise HTTPException(
            status_code=429,
            detail={"code": "agent_run_sse_capacity_exceeded"},
            headers={"Retry-After": "1"},
        )
    try:
        resume_sequence = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        resume_sequence = 0

    async def event_stream():
        sequence = max(0, after_sequence, resume_sequence)
        idle_delay = 0.25
        try:
            while True:
                raw_events, run, projection_ready, has_dispatch = await asyncio.to_thread(
                    store.read_agent_run_event_page,
                    run_id,
                    after_sequence=sequence,
                    limit=100,
                )
                events = [_public_agent_run_event(event) for event in raw_events]
                for event in events:
                    sequence = event.sequence
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {event.model_dump_json()}\n\n"
                if run is None or (
                    run.status.value in _TERMINAL
                    and len(events) < 100
                    and (not has_dispatch or projection_ready)
                ):
                    break
                if len(events) == 100:
                    idle_delay = 0.25
                    continue
                if events:
                    idle_delay = 0.25
                await asyncio.sleep(idle_delay)
                idle_delay = min(idle_delay * 2, 2.0)
        finally:
            _sse_capacity.release(user_id=user.id, run_id=run_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{run_id}/cancel", response_model=ItemResponse)
async def cancel_agent_run(run_id: str, user: User = Depends(current_user)) -> ItemResponse:
    from agentmesh.routes.chat import agent

    run = _visible_run(run_id, user)
    if run.orchestration_version == "research-v2":
        raise HTTPException(status_code=409, detail=_RESEARCH_V2_READ_ONLY)
    if run.orchestration_version == "research-v3":
        raise HTTPException(status_code=409, detail=_RESEARCH_V3_RETIRED)
    runtime = agent.agent_runtime
    if runtime is None:
        raise HTTPException(status_code=409, detail="Agent Runtime v2 is disabled")
    try:
        run = await runtime.cancel(run_id, user=user)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return ItemResponse(item=run)
