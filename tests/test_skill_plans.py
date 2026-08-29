from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from agents.testing import ScriptedModel
from fastapi import HTTPException
from fastapi.testclient import TestClient

import agentmesh.routes.agent_runs as agent_run_routes
import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.app import app
from agentmesh.models import (
    AgentRun,
    AgentRunCreateRequest,
    AgentRunRetryRequest,
    AgentRunStatus,
    ChatThread,
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillIntent,
    SkillIntentComplexity,
    SkillIntentConstraints,
    SkillLifecycleStage,
    SkillNodeResult,
    SkillPlan,
    SkillPlanDraft,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillPlanVersionRequest,
    SkillSideEffect,
    now_utc,
)
from agentmesh.seed import TEAM_LEAD, USER, ensure_base_workspace_data
from agentmesh.skill_runtime.executor import PlanExecutionOutcome
from agentmesh.skill_runtime.plan_validation import PlanValidationError, validate_draft
from agentmesh.skill_runtime.planner import PlannerUnavailable, SkillPlanner, single_skill_draft
from agentmesh.skill_runtime.service import SkillCatalogService, catalog_service
from agentmesh.store import SQLiteStore, store


def _node(skill_id: str = "skill_a", *, status: SkillPlanNodeStatus = SkillPlanNodeStatus.PENDING) -> SkillPlanNode:
    return SkillPlanNode(
        id=f"node_{skill_id}",
        skill_id=skill_id,
        skill_version="1",
        skill_content_hash=f"hash_{skill_id}",
        reason="required for the requested output",
        input_bindings=["user.design_requirement"],
        output_contract=["design_analysis"],
        status=status,
    )


def _plan(run_id: str = "run_plan_store", *, node: SkillPlanNode | None = None) -> SkillPlan:
    return SkillPlan(
        id=f"plan_{run_id}",
        run_id=run_id,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(goal="analyze a design request", deliverables=["design_analysis"]),
        candidate_skill_ids=[(node or _node()).skill_id],
        output_contract=["design_analysis"],
        nodes=[node or _node()],
    )


def _candidate(
    skill_id: str,
    *,
    inputs: list[str],
    outputs: list[str],
) -> SkillCandidate:
    return SkillCandidate(
        skill_id=skill_id,
        skill_name=skill_id,
        title=skill_id,
        description=skill_id,
        profile=SkillCapabilityProfile(
            id=f"profile_{skill_id}",
            skill_id=skill_id,
            skill_name=skill_id,
            skill_version="1",
            skill_content_hash=f"hash_{skill_id}",
            profile_version="1",
            profile_content_hash=f"profile_hash_{skill_id}",
            primary_stage=SkillLifecycleStage.PRE_DESIGN,
            capability_type=SkillCapabilityType.ANALYSIS,
            input_kinds=inputs,
            output_kinds=outputs,
        ),
        score=SkillCandidateScore(),
        reason="test candidate",
    )


def _approval_plan(repository: SQLiteStore, *, suffix: str) -> tuple[AgentRun, SkillPlan, SkillCandidate]:
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    candidate = _candidate("approval_skill", inputs=["design_requirement"], outputs=["design_analysis"])
    run = repository.save_agent_run(
        AgentRun(
            id=f"run_approval_{suffix}",
            thread_id=f"thread_approval_{suffix}",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="approve safely",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            orchestration_mode="execute",
        )
    )
    node = SkillPlanNode(
        id=f"node_approval_{suffix}",
        skill_id=candidate.skill_id,
        skill_version=candidate.profile.skill_version,
        skill_content_hash=candidate.profile.skill_content_hash,
        reason="produce the requested analysis",
        input_bindings=["user.design_requirement"],
        output_contract=["design_analysis"],
        side_effect=candidate.profile.side_effect,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=f"plan_approval_{suffix}",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(
                goal="approve safely",
                input_kinds=["design_requirement"],
                deliverables=["design_analysis"],
            ),
            candidate_skill_ids=[candidate.skill_id],
            output_contract=["design_analysis"],
            nodes=[node],
        )
    )
    run.plan_id = plan.id
    repository.save_agent_run(run)
    return run, plan, candidate


def test_plan_validation_rejects_inputs_unsupported_by_the_consumer() -> None:
    producer = _candidate("producer", inputs=["prd"], outputs=["analysis"])
    consumer = _candidate("consumer", inputs=["research_plan"], outputs=["report"])
    draft = SkillPlanDraft(
        output_contract=["report"],
        nodes=[
            SkillPlanNode(
                id="producer_node",
                skill_id=producer.skill_id,
                skill_version="1",
                skill_content_hash="hash_producer",
                reason="produce analysis",
                input_bindings=["user.prd"],
                output_contract=["analysis"],
            ),
            SkillPlanNode(
                id="consumer_node",
                skill_id=consumer.skill_id,
                skill_version="1",
                skill_content_hash="hash_consumer",
                reason="consume analysis",
                depends_on=["producer_node"],
                input_bindings=["producer_node.analysis", "user.prd"],
                output_contract=["report"],
            ),
        ],
    )

    with pytest.raises(PlanValidationError) as error:
        validate_draft(draft, [producer, consumer], intent=SkillIntent(goal="test", input_kinds=["prd"]))

    assert error.value.codes == ["unsupported_node_input"]


def test_direct_plan_rejects_an_unsupported_deliverable() -> None:
    candidate = _candidate("analysis", inputs=["prd"], outputs=["analysis"])
    intent = SkillIntent(goal="produce a report", input_kinds=["prd"], deliverables=["report"])

    with pytest.raises(PlannerUnavailable, match="cannot satisfy"):
        single_skill_draft(intent, candidate)


def test_plan_version_cas_and_node_claim_are_atomic(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "plans.sqlite3")
    repository.save_agent_run(
        AgentRun(
            id="run_plan_store",
            thread_id="thread_plan_store",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="edit plan",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        )
    )
    plan = repository.save_skill_plan(_plan())
    first = plan.model_copy(deep=True)
    second = plan.model_copy(deep=True)

    assert repository.compare_and_swap_skill_plan(first, expected_version=1) is True
    assert first.version == 2
    assert repository.compare_and_swap_skill_plan(second, expected_version=1) is False

    ready_plan = _plan("run_claim", node=_node(status=SkillPlanNodeStatus.READY))
    ready_plan.status = SkillPlanStatus.RUNNING
    repository.save_agent_run(
        AgentRun(
            id=ready_plan.run_id,
            thread_id="thread_claim",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="claim",
            status=AgentRunStatus.RUNNING,
        )
    )
    repository.save_skill_plan(ready_plan)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(
            executor.map(
                lambda _: repository.claim_skill_plan_node(ready_plan.id, ready_plan.nodes[0].id),
                range(2),
            )
        )
    claimed = [item for item in claims if item is not None]
    assert len(claimed) == 1
    assert claimed[0].attempt == 1
    assert claimed[0].status == SkillPlanNodeStatus.RUNNING


def test_plan_patch_cannot_revive_a_cancelled_run(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "cancelled-plan-cas.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_cancelled_plan_cas",
            thread_id="thread_cancelled_plan_cas",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="cancel before stale patch",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        )
    )
    plan = repository.save_skill_plan(_plan(run.id))
    stale = plan.model_copy(deep=True)

    assert repository.cancel_agent_run_tree(run.id, user_id=USER.id) is not None
    assert repository.compare_and_swap_skill_plan(stale, expected_version=1) is False
    assert repository.get_agent_run(run.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status == SkillPlanStatus.CANCELLED  # type: ignore[union-attr]


def test_exhausted_node_attempt_cannot_be_claimed_or_corrupt_plan(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "exhausted-node.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_exhausted_node",
            thread_id="thread_exhausted_node",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="do not claim attempt three",
            status=AgentRunStatus.RUNNING,
        )
    )
    node = _node(status=SkillPlanNodeStatus.READY).model_copy(update={"attempt": 2})
    plan = _plan(run.id, node=node).model_copy(update={"status": SkillPlanStatus.RUNNING})
    repository.save_skill_plan(plan)

    assert repository.claim_skill_plan_node(plan.id, node.id) is None
    persisted = repository.get_skill_plan(plan.id)
    assert persisted is not None and persisted.nodes[0].attempt == 2


def test_plan_execution_claim_and_node_results_are_exactly_once(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "plan-exactly-once.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_plan_exactly_once",
            thread_id="thread_plan_exactly_once",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="execute",
            status=AgentRunStatus.RUNNING,
        )
    )
    plan = _plan(run.id)
    plan.status = SkillPlanStatus.APPROVED
    repository.save_skill_plan(plan)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: repository.claim_skill_plan_for_execution(plan.id, run.id), range(2)))

    assert sum(item is not None for item in claims) == 1
    result = SkillNodeResult(
        id="result_exactly_once",
        node_id=plan.nodes[0].id,
        skill_id=plan.nodes[0].skill_id,
        summary="immutable",
        attempt=1,
    )
    repository.save_skill_node_result(plan.id, result)
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_skill_node_result(plan.id, result.model_copy(update={"summary": "overwritten"}))
    assert repository.list_skill_node_results(plan.id)[0].summary == "immutable"


def test_terminal_transition_preserves_concurrently_completed_node(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "stale-plan.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_stale_plan",
            thread_id="thread_stale_plan",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="execute",
            status=AgentRunStatus.RUNNING,
        )
    )
    node = _node(status=SkillPlanNodeStatus.READY)
    plan = _plan(run.id, node=node)
    plan.status = SkillPlanStatus.RUNNING
    repository.save_skill_plan(plan)
    stale_plan = plan.model_copy(deep=True)
    stale_run = run.model_copy(deep=True)
    claimed = repository.claim_skill_plan_node(plan.id, node.id)
    assert claimed is not None
    result = SkillNodeResult(
        id="result_stale_plan",
        node_id=claimed.id,
        skill_id=claimed.skill_id,
        summary="completed before cancellation",
        attempt=claimed.attempt,
    )
    completed = claimed.model_copy(update={"status": SkillPlanNodeStatus.COMPLETED})
    assert repository.transition_skill_plan_node(
        plan_id=plan.id,
        run_id=run.id,
        node=completed,
        expected_statuses={SkillPlanNodeStatus.RUNNING},
        event_type="node_completed",
        event_payload={"node_id": node.id},
        result=result,
    ) is not None

    stale_plan.nodes[0].status = SkillPlanNodeStatus.CANCELLED
    stale_plan.status = SkillPlanStatus.CANCELLED
    stale_run.status = AgentRunStatus.CANCELLED
    transitioned = repository.finish_skill_plan_and_run(
        plan=stale_plan,
        run=stale_run,
        expected_plan_statuses={SkillPlanStatus.RUNNING},
        expected_run_statuses={AgentRunStatus.RUNNING},
        events=[("run_cancelled", {})],
    )

    assert transitioned is not None
    persisted = repository.get_skill_plan(plan.id)
    assert persisted is not None and persisted.nodes[0].status == SkillPlanNodeStatus.COMPLETED
    assert repository.list_skill_node_results(plan.id) == [result]


def test_plan_and_run_transition_persists_terminal_event_atomically(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "transition.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_preview_transition",
            thread_id="thread_preview_transition",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="preview",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            orchestration_mode="preview",
        )
    )
    plan = repository.save_skill_plan(_plan(run.id))

    transitioned = repository.transition_skill_plan_and_run(
        plan_id=plan.id,
        run_id=run.id,
        expected_version=1,
        expected_plan_status=SkillPlanStatus.WAITING_APPROVAL,
        expected_run_status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        next_plan_status=SkillPlanStatus.APPROVED,
        next_run_status=AgentRunStatus.COMPLETED,
        events=[("plan_approved", {"plan_id": plan.id}), ("run_completed", {"preview_only": True})],
    )

    assert transitioned is not None
    assert repository.get_agent_run(run.id).status == AgentRunStatus.COMPLETED  # type: ignore[union-attr]
    assert [event.event_type for event in repository.list_agent_run_events(run.id)] == [
        "plan_approved",
        "run_completed",
    ]


def test_plan_api_supports_limited_adjustment_and_preview_approval(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    configure_pilot_wiki(tmp_path / "wiki")
    catalog = catalog_service()
    catalog.reload()
    prd = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    interview = catalog.get_by_name("generate-interview-guide", USER.personal_agent_id)
    assert prd is not None and interview is not None
    prd_profile = store.get_skill_capability_profile(prd.id)
    interview_profile = store.get_skill_capability_profile(interview.id)
    assert prd_profile is not None and interview_profile is not None
    run = store.save_agent_run(
        AgentRun(
            id="run_plan_api_preview",
            thread_id="thread_plan_api_preview",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="review a PRD and optionally prepare interviews",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            orchestration_mode="preview",
            project_chat=True,
        )
    )
    plan = store.save_skill_plan(
        SkillPlan(
            id="plan_api_preview",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(
                goal="评审 PRD 并准备用户访谈",
                input_kinds=["prd"],
                deliverables=["feasibility_review"],
            ),
            candidate_skill_ids=[prd.id, interview.id],
            output_contract=["feasibility_review"],
            nodes=[
                SkillPlanNode(
                    id="node_api_prd",
                    skill_id=prd.id,
                    skill_version=prd.version,
                    skill_content_hash=prd.content_hash,
                    reason="review the PRD",
                    required=True,
                    input_bindings=["user.prd"],
                    output_contract=["feasibility_review"],
                    side_effect=prd_profile.side_effect,
                ),
                SkillPlanNode(
                    id="node_api_interview",
                    skill_id=interview.id,
                    skill_version=interview.version,
                    skill_content_hash=interview.content_hash,
                    reason="prepare optional interviews",
                    required=False,
                    input_bindings=["user.request"],
                    output_contract=["interview_guide"],
                    side_effect=interview_profile.side_effect,
                ),
            ],
        )
    )
    run.plan_id = plan.id
    store.save_agent_run(run)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"}).status_code == 200

    adjusted = client.patch(
        f"/api/agent/runs/{run.id}/plan",
        json={"expected_version": 1, "selected_skill_ids": [prd.id], "preferred_order": [prd.id]},
    )
    approved = client.post(
        f"/api/agent/runs/{run.id}/plan/approve",
        json={"expected_version": 2},
    )

    assert adjusted.status_code == 200
    assert adjusted.json()["plan"]["version"] == 2
    assert [node["skill_id"] for node in adjusted.json()["plan"]["nodes"]] == [prd.id]
    assert approved.status_code == 200
    assert approved.json()["run"]["status"] == "completed"
    assert approved.json()["plan"]["status"] == "approved"
    assert store.list_thread_messages(run.thread_id)[-1].role == "assistant"

    assert client.post("/api/auth/login", json={"user_id": TEAM_LEAD.id, "password": "lead123"}).status_code == 200
    assert client.get(f"/api/agent/runs/{run.id}/plan").status_code == 404


def test_orchestrated_retry_revalidates_plan_and_reuses_only_side_effect_free_results(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    configure_pilot_wiki(tmp_path / "retry-wiki")
    repository = SQLiteStore(tmp_path / "orchestration-retry.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    prd = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    interview = catalog.get_by_name("generate-interview-guide", USER.personal_agent_id)
    survey = catalog.get_by_name("generate-survey", USER.personal_agent_id)
    assert prd is not None and interview is not None and survey is not None
    prd_profile = repository.get_skill_capability_profile(prd.id)
    interview_profile = repository.get_skill_capability_profile(interview.id)
    survey_profile = repository.get_skill_capability_profile(survey.id)
    assert prd_profile is not None and interview_profile is not None and survey_profile is not None
    repository.save_skill_capability_profile(
        interview_profile.model_copy(update={"side_effect": SkillSideEffect.EXTERNAL_WRITE})
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_orchestration_retry",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Retry safely",
        )
    )
    prior_run = repository.save_agent_run(
        AgentRun(
            id="run_orchestration_retry_prior",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="评审 PRD，准备访谈并生成问卷",
            status=AgentRunStatus.PARTIAL,
            plan_id="plan_orchestration_retry_prior",
            orchestration_mode="execute",
        )
    )
    nodes = [
        SkillPlanNode(
            id="node_retry_prd",
            skill_id=prd.id,
            skill_version=prd.version,
            skill_content_hash=prd.content_hash,
            reason="review PRD",
            input_bindings=["user.prd"],
            output_contract=["feasibility_review"],
            side_effect=prd_profile.side_effect,
            status=SkillPlanNodeStatus.COMPLETED,
            attempt=1,
        ),
        SkillPlanNode(
            id="node_retry_interview",
            skill_id=interview.id,
            skill_version=interview.version,
            skill_content_hash=interview.content_hash,
            reason="publish interview guide",
            input_bindings=["user.request"],
            output_contract=["interview_guide"],
            side_effect=SkillSideEffect.EXTERNAL_WRITE,
            status=SkillPlanNodeStatus.COMPLETED,
            attempt=1,
        ),
        SkillPlanNode(
            id="node_retry_survey",
            skill_id=survey.id,
            skill_version=survey.version,
            skill_content_hash=survey.content_hash,
            reason="generate optional survey",
            required=False,
            input_bindings=["user.request"],
            output_contract=["survey"],
            side_effect=survey_profile.side_effect,
            status=SkillPlanNodeStatus.FAILED,
            attempt=1,
            error_code="provider_error",
        ),
    ]
    prior_plan = repository.save_skill_plan(
        SkillPlan(
            id=prior_run.plan_id,
            run_id=prior_run.id,
            status=SkillPlanStatus.PARTIAL,
            intent=SkillIntent(
                goal=prior_run.input_text,
                input_kinds=["prd"],
                deliverables=["feasibility_review", "interview_guide", "survey"],
                constraints=SkillIntentConstraints(external_write=True),
                complexity=SkillIntentComplexity.WORKFLOW,
            ),
            candidate_skill_ids=[prd.id, interview.id, survey.id],
            output_contract=["feasibility_review"],
            nodes=nodes,
        )
    )
    for node in nodes[:2]:
        repository.save_skill_node_result(
            prior_plan.id,
            SkillNodeResult(
                id=f"result_prior_{node.id}",
                node_id=node.id,
                skill_id=node.skill_id,
                summary=f"completed {node.id}",
                reused_from_run_id="run_original_source" if node.id == "node_retry_prd" else None,
                reused_from_result_id="result_original_source" if node.id == "node_retry_prd" else None,
                attempt=1,
            ),
        )
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True, skill_catalog=catalog)

    retried = asyncio.run(
        runtime.retry_orchestrated(
            prior_run=prior_run,
            prior_plan=prior_plan,
            user=USER,
            client_turn_id="turn_orchestration_retry",
            mode=SkillOrchestrationMode.EXECUTE,
        )
    )
    repeated = asyncio.run(
        runtime.retry_orchestrated(
            prior_run=prior_run,
            prior_plan=prior_plan,
            user=USER,
            client_turn_id="turn_orchestration_retry",
            mode=SkillOrchestrationMode.EXECUTE,
        )
    )

    assert repeated.id == retried.id
    assert retried.id != prior_run.id
    assert retried.retry_of_run_id == prior_run.id
    assert retried.project_id == prior_run.project_id
    assert retried.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    retry_plan = repository.get_skill_plan_for_run(retried.id)
    assert retry_plan is not None and retry_plan.status == SkillPlanStatus.WAITING_APPROVAL
    assert {node.id: node.status for node in retry_plan.nodes} == {
        "node_retry_prd": SkillPlanNodeStatus.COMPLETED,
        "node_retry_interview": SkillPlanNodeStatus.PENDING,
        "node_retry_survey": SkillPlanNodeStatus.PENDING,
    }
    reused = repository.list_skill_node_results(retry_plan.id)
    assert len(reused) == 1
    assert reused[0].node_id == "node_retry_prd"
    assert reused[0].reused_from_run_id == "run_original_source"
    assert reused[0].reused_from_result_id == "result_original_source"
    assert len(repository.list_thread_messages(thread.id)) == 1


def test_multi_skill_plan_does_not_build_tools_before_approval(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "planning-wiki")
    repository = SQLiteStore(tmp_path / "planning.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()

    class IntentAnalyzerStub:
        async def analyze(self, *_args, **_kwargs):
            return (
                SkillIntent(
                    goal="评审 PRD 并准备访谈",
                    input_kinds=["prd"],
                    deliverables=["feasibility_review", "interview_guide"],
                    complexity=SkillIntentComplexity.ASSISTED,
                ),
                [],
            )

    async def draft_factory(intent, candidates):
        del intent
        selected = [
            next(candidate for candidate in candidates if candidate.skill_name == "prd-feasibility"),
            next(candidate for candidate in candidates if candidate.skill_name == "generate-interview-guide"),
        ]
        return SkillPlanDraft(
            output_contract=["feasibility_review", "interview_guide"],
            nodes=[
                SkillPlanNode(
                    id=f"node_{index}",
                    skill_id=candidate.skill_id,
                    skill_version=candidate.profile.skill_version,
                    skill_content_hash=candidate.profile.skill_content_hash,
                    reason=candidate.reason,
                    required=True,
                    input_bindings=["user.prd"] if "prd" in candidate.profile.input_kinds else ["user.request"],
                    output_contract=[candidate.profile.output_kinds[0]],
                    side_effect=candidate.profile.side_effect,
                )
                for index, candidate in enumerate(selected)
            ],
        )

    class ToolFactoryTrap:
        def __init__(self):
            self.calls = 0

        def build(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("tools must not be built during planning")

    trap = ToolFactoryTrap()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        tool_factory=trap,  # type: ignore[arg-type]
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzerStub(),  # type: ignore[arg-type]
        skill_planner=SkillPlanner(draft_factory=draft_factory),
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_no_tools_before_plan_approval",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Plan safely",
        )
    )

    async def scenario():
        run = await runtime.start_orchestrated(
            content="评审 PRD 并准备访谈",
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_no_tools_before_plan_approval",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        task = runtime._tasks[run.id]
        await task
        return repository.get_agent_run(run.id)

    run = asyncio.run(scenario())

    assert run is not None
    assert run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    assert trap.calls == 0


def test_planner_initial_exception_gets_one_repair_attempt(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "planner-repair-wiki")
    repository = SQLiteStore(tmp_path / "planner-repair.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    calls = 0

    class IntentAnalyzerStub:
        async def analyze(self, *_args, **_kwargs):
            return (
                SkillIntent(
                    goal="评审 PRD 并准备访谈",
                    input_kinds=["prd"],
                    deliverables=["feasibility_review", "interview_guide"],
                    complexity=SkillIntentComplexity.ASSISTED,
                ),
                [],
            )

    async def draft_factory(_intent, candidates):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first planner response was invalid")
        selected = [
            next(candidate for candidate in candidates if candidate.skill_name == "prd-feasibility"),
            next(candidate for candidate in candidates if candidate.skill_name == "generate-interview-guide"),
        ]
        return SkillPlanDraft(
            output_contract=["feasibility_review", "interview_guide"],
            nodes=[
                SkillPlanNode(
                    id=f"node_repaired_{index}",
                    skill_id=candidate.skill_id,
                    skill_version=candidate.profile.skill_version,
                    skill_content_hash=candidate.profile.skill_content_hash,
                    reason=candidate.reason,
                    input_bindings=["user.prd"] if "prd" in candidate.profile.input_kinds else ["user.request"],
                    output_contract=[candidate.profile.output_kinds[0]],
                    side_effect=candidate.profile.side_effect,
                )
                for index, candidate in enumerate(selected)
            ],
        )

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzerStub(),  # type: ignore[arg-type]
        skill_planner=SkillPlanner(draft_factory=draft_factory),
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_planner_repair",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Repair planner",
        )
    )

    async def scenario():
        run = await runtime.start_orchestrated(
            content="评审 PRD 并准备访谈",
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_planner_repair",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        await runtime._tasks[run.id]
        return repository.get_agent_run(run.id)

    run = asyncio.run(scenario())

    assert calls == 2
    assert run is not None and run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    assert repository.get_skill_plan_for_run(run.id) is not None


def test_planner_repeated_exception_uses_safe_single_skill_fallback(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    configure_pilot_wiki(tmp_path / "planner-fallback-wiki")
    repository = SQLiteStore(tmp_path / "planner-fallback.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    calls = 0

    class IntentAnalyzerStub:
        async def analyze(self, *_args, **_kwargs):
            return (
                SkillIntent(
                    goal="评审 PRD 的可行性与风险",
                    input_kinds=["prd"],
                    deliverables=["feasibility_review", "risk_analysis"],
                    complexity=SkillIntentComplexity.ASSISTED,
                ),
                [],
            )

    async def draft_factory(_intent, _candidates):
        nonlocal calls
        calls += 1
        raise RuntimeError("planner unavailable")

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzerStub(),  # type: ignore[arg-type]
        skill_planner=SkillPlanner(draft_factory=draft_factory),
    )

    async def fake_execute(*, plan, run, user, resume=False):
        del user, resume
        return PlanExecutionOutcome(plan=plan, run=run)

    runtime._execute_approved_skill_plan = fake_execute  # type: ignore[method-assign]
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_planner_fallback",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Fallback planner",
        )
    )

    async def scenario():
        run = await runtime.start_orchestrated(
            content="评审 PRD 的可行性与风险",
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_planner_fallback",
            mode=SkillOrchestrationMode.EXECUTE,
        )
        await runtime._tasks[run.id]
        return run

    run = asyncio.run(scenario())
    plan = repository.get_skill_plan_for_run(run.id)

    assert calls == 2
    assert plan is not None and len(plan.nodes) == 1
    assert plan.degradation == "planner_validation_fallback_single"
    assert plan.nodes[0].skill_id == next(
        skill.id for skill in repository.skill_definitions if skill.name == "prd-feasibility"
    )


def test_intent_stage_respects_parent_deadline(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "intent-deadline.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)

    class BlockingIntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        intent_analyzer=BlockingIntentAnalyzer(),  # type: ignore[arg-type]
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_intent_deadline",
            thread_id="thread_intent_deadline",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="plan before deadline",
            status=AgentRunStatus.PLANNING,
            deadline_at=now_utc() + timedelta(milliseconds=20),
        )
    )
    selected = runtime._select_model(USER)
    assert selected is not None

    with pytest.raises(TimeoutError):
        asyncio.run(
            runtime._prepare_orchestration(
                run=run,
                selected=selected,
                content=run.input_text,
                user=USER,
                history=[],
                mode=SkillOrchestrationMode.EXECUTE,
            )
        )

    failed = repository.get_agent_run(run.id)
    assert failed is not None and failed.status == AgentRunStatus.FAILED


def test_orchestration_rechecks_project_access_after_intent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "intent-revocation.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_intent_revocation",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Revoke during intent",
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_intent_revocation",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="生成研究计划",
            status=AgentRunStatus.PLANNING,
            deadline_at=now_utc() + timedelta(seconds=300),
        )
    )
    intent_calls = 0

    class RevokingIntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            nonlocal intent_calls
            intent_calls += 1
            project = repository.get_project(USER.default_project_id)
            assert project is not None
            repository.save_project(project.model_copy(update={"member_ids": ["usr_someone_else"]}))
            return SkillIntent(goal="生成研究计划"), []

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        intent_analyzer=RevokingIntentAnalyzer(),  # type: ignore[arg-type]
    )
    selected = runtime._select_model(USER)
    assert selected is not None

    with pytest.raises(RuntimeError, match="planned_project_access_revoked"):
        asyncio.run(
            runtime._prepare_orchestration(
                run=run,
                selected=selected,
                content=run.input_text,
                user=USER,
                history=[],
                mode=SkillOrchestrationMode.EXECUTE,
            )
        )

    persisted = repository.get_agent_run(run.id)
    assert intent_calls == 1
    assert persisted is not None and persisted.status == AgentRunStatus.FAILED
    assert repository.get_skill_plan_for_run(run.id) is None


def test_plan_approval_is_rejected_without_mutation_when_orchestration_is_off(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "approval-off.sqlite3")
    run, plan, candidate = _approval_plan(repository, suffix="off")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "_current_plan_candidates", lambda *_args: [candidate])

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    assert error.value.status_code == 409
    assert error.value.detail == {"code": "skill_orchestration_disabled"}
    assert repository.get_agent_run(run.id).status == AgentRunStatus.WAITING_PLAN_APPROVAL  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status == SkillPlanStatus.WAITING_APPROVAL  # type: ignore[union-attr]


def test_plan_rejection_projects_terminal_message_once(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "rejection-projection.sqlite3")
    run, plan, _candidate = _approval_plan(repository, suffix="reject_projection")
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    response = agent_run_routes.reject_agent_run_plan(
        run.id,
        SkillPlanVersionRequest(expected_version=plan.version),
        user=USER,
    )

    assert response.run.status is AgentRunStatus.REJECTED
    receipt = repository.get_run_output_projection(run.id)
    assert receipt is not None and receipt.disposition == "message"
    assert receipt.terminal_status is AgentRunStatus.REJECTED
    messages = repository.list_thread_messages(run.thread_id)
    assert len([message for message in messages if message.role.value == "assistant"]) == 1
    _events, _stored_run, projection_ready, has_dispatch = (
        repository.read_agent_run_event_page(run.id, after_sequence=0, limit=100)
    )
    assert projection_ready is True
    assert has_dispatch is False


def test_plan_rejection_is_rejected_without_mutation_when_orchestration_is_off(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "rejection-off.sqlite3")
    run, plan, _candidate = _approval_plan(repository, suffix="reject_off")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setattr(agent_run_routes, "store", repository)

    with pytest.raises(HTTPException) as error:
        agent_run_routes.reject_agent_run_plan(
            run.id,
            SkillPlanVersionRequest(expected_version=plan.version),
            user=USER,
        )

    assert error.value.detail == {"code": "skill_orchestration_disabled"}
    assert repository.get_agent_run(run.id).status == AgentRunStatus.WAITING_PLAN_APPROVAL  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status == SkillPlanStatus.WAITING_APPROVAL  # type: ignore[union-attr]


def test_plan_approval_cancels_waiting_run_when_runtime_is_disabled(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "approval-runtime-disabled.sqlite3")
    run, plan, candidate = _approval_plan(repository, suffix="runtime_disabled")

    class DisabledRuntime:
        enabled = False

    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "_current_plan_candidates", lambda *_args: [candidate])
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", DisabledRuntime())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    assert error.value.status_code == 409
    assert repository.get_agent_run(run.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status == SkillPlanStatus.CANCELLED  # type: ignore[union-attr]


def test_plan_approval_cancels_transition_when_execution_start_races_with_rollback(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "approval-race.sqlite3")
    run, plan, candidate = _approval_plan(repository, suffix="race")
    starts = 0

    class RacingRuntime:
        enabled = True

        async def start_approved_skill_plan(self, _plan_id: str, *, user) -> None:  # noqa: ANN001
            del user
            nonlocal starts
            starts += 1
            raise RuntimeError("Skill orchestration execution is disabled")

    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "_current_plan_candidates", lambda *_args: [candidate])
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", RacingRuntime())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    assert starts == 1
    assert error.value.status_code == 409
    assert repository.get_agent_run(run.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status == SkillPlanStatus.CANCELLED  # type: ignore[union-attr]


def test_run_plan_and_retry_reject_revoked_run_project(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "revoked-run-project-routes.sqlite3")
    ensure_base_workspace_data(repository)
    original_project = repository.get_project(USER.default_project_id)
    assert original_project is not None
    alternate_project = original_project.model_copy(
        update={
            "id": "prj_alternate_for_revoked_run",
            "name": "Alternate project",
            "goal": "Keep the current default project accessible",
            "member_ids": [USER.id],
        }
    )
    repository.save_project(alternate_project)
    user = USER.model_copy(update={"default_project_id": alternate_project.id})
    repository.save_user(user)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_revoked_run_project",
            workspace_id=USER.workspace_id,
            project_id=original_project.id,
            user_id=USER.id,
            title="Revoked run project",
        )
    )
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id="run_revoked_run_project",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=original_project.id,
            input_text="do not expose old project history",
            client_turn_id="turn_revoked_run_project",
            output_text="revoked project result",
            status=AgentRunStatus.FAILED,
            plan_id="plan_run_revoked_run_project",
            orchestration_mode="execute",
        )
    )
    assert created is True
    plan = _plan(run.id).model_copy(
        update={"id": run.plan_id, "status": SkillPlanStatus.FAILED}
    )
    repository.save_skill_plan(plan)
    repository.save_project(original_project.model_copy(update={"member_ids": ["usr_someone_else"]}))
    monkeypatch.setattr(agent_run_routes, "store", repository)
    assert chat_routes.agent.agent_runtime is not None
    monkeypatch.setattr(chat_routes.agent.agent_runtime, "_enabled_override", True)

    with pytest.raises(HTTPException) as create_error:
        asyncio.run(
            agent_run_routes.start_agent_run(
                AgentRunCreateRequest(
                    content=run.input_text,
                    client_turn_id=run.client_turn_id,
                ),
                user=user,
            )
        )
    with pytest.raises(HTTPException) as run_error:
        agent_run_routes.get_agent_run(run.id, user=user)
    with pytest.raises(HTTPException) as plan_error:
        agent_run_routes.get_agent_run_plan(run.id, user=user)
    with pytest.raises(HTTPException) as retry_error:
        asyncio.run(
            agent_run_routes.retry_agent_run(
                run.id,
                AgentRunRetryRequest(client_turn_id="turn_retry_revoked_run_project"),
                user=user,
            )
        )

    assert [
        create_error.value.status_code,
        run_error.value.status_code,
        plan_error.value.status_code,
        retry_error.value.status_code,
    ] == [404, 404, 404, 404]
    assert [item.id for item in repository.list_agent_runs(USER.id)] == [run.id]


def test_plan_approval_rejects_revoked_project_without_transition(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "approval-project-revocation.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    run = repository.save_agent_run(
        AgentRun(
            id="run_approval_project_revocation",
            thread_id="thread_approval_project_revocation",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="approve safely",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
        )
    )
    plan = repository.save_skill_plan(_plan(run.id))
    run.plan_id = plan.id
    repository.save_agent_run(run)
    project = repository.get_project(USER.default_project_id)
    assert project is not None
    repository.save_project(project.model_copy(update={"member_ids": ["usr_someone_else"]}))
    monkeypatch.setattr(agent_run_routes, "store", repository)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    persisted_run = repository.get_agent_run(run.id)
    persisted_plan = repository.get_skill_plan(plan.id)
    assert error.value.status_code == 404
    assert persisted_run is not None and persisted_run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    assert persisted_plan is not None and persisted_plan.status == SkillPlanStatus.WAITING_APPROVAL


def test_expired_plan_approval_is_cancelled() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_expired_plan_approval",
            thread_id="thread_expired_plan_approval",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="expired plan",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            deadline_at=now_utc() - timedelta(seconds=1),
        )
    )
    plan = store.save_skill_plan(_plan(run.id))
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"}).status_code == 200

    response = client.post(f"/api/agent/runs/{run.id}/plan/approve", json={"expected_version": 1})

    assert response.status_code == 409
    assert store.get_agent_run(run.id).status == AgentRunStatus.CANCELLED  # type: ignore[union-attr]
    assert store.get_skill_plan(plan.id).status == SkillPlanStatus.CANCELLED  # type: ignore[union-attr]
