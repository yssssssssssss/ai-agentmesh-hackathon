from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from agents.testing import ScriptedModel

import agentmesh.routes.agent_runs as agent_run_routes
import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import (
    AgentRuntimeService,
    _StandardSkillNodeResultDraft,
)
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.models import (
    AgentExecutionContractVersion,
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRunStatus,
    SkillDefinition,
    SkillIntent,
    SkillIntentComplexity,
    SkillPlanVersionRequest,
    SkillSourceScope,
    SkillSynthesisResult,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime import universal_execution
from agentmesh.skill_runtime.executor import NodeExecutionOutcome
from agentmesh.skill_runtime.profiles import load_capability_profile_record
from agentmesh.skill_runtime.recommendation import UniversalSkillSearchService
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def _catalog(
    tmp_path: Path,
    *,
    output_kinds: list[str] | None = None,
) -> tuple[SQLiteStore, SkillCatalogService, SkillDefinition]:
    output_kinds = output_kinds or ["analysis_result"]
    repository = SQLiteStore(tmp_path / "universal-preview.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    root = tmp_path / "universal-preview-skill"
    (root / "agents").mkdir(parents=True)
    skill_path = root / "SKILL.md"
    skill_path.write_text(
        """---
name: universal-preview-skill
description: Analyze a bounded product request.
metadata:
  version: "1"
---
# Universal Preview Skill
""",
        encoding="utf-8",
    )
    content_hash = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    skill = SkillDefinition(
        id="skill_universal_preview",
        name="universal-preview-skill",
        title="Universal Preview Skill",
        description="Analyze a bounded product request.",
        instructions="# Universal Preview Skill",
        source_path=str(skill_path),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=content_hash,
        version="1",
    )
    (root / "agents" / "agentmesh.yaml").write_text(
        yaml.safe_dump(
            {
                "skill_id": "auto",
                "skill_version": "1",
                "skill_content_hash": content_hash,
                "profile_version": "1",
                "display_description": "Analyze a bounded product request.",
                "primary_stage": "pre_design",
                "capability_type": "analysis",
                "input_kinds": ["request"],
                "output_kinds": output_kinds,
                "examples": ["Analyze this product", "Review this product", "Assess this product"],
                "negative_examples": ["Book a flight", "Write production data"],
                "required_tools": [],
                "required_resources": [],
                "owner": "@owner",
                "review_state": "approved",
                "side_effect": "draft",
                "planner_eligible": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(
        load_capability_profile_record(skill).profile,
        defer_vector=True,
    )
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}
    return repository, catalog, skill


def test_planning_contract_selection_is_mode_specific_and_direct_runs_stay_unmarked(tmp_path) -> None:
    repository, catalog, _skill = _catalog(tmp_path)
    legacy = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        universal_preview_enabled=False,
    )
    universal = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        universal_preview_enabled=True,
    )

    assert legacy.planning_contract_for(
        planning_mode=AgentPlanningMode.STANDARD,
        planned=True,
    ) is AgentPlanningContractVersion.STANDARD_LEGACY_V1
    assert universal.planning_contract_for(
        planning_mode=AgentPlanningMode.STANDARD,
        planned=True,
    ) is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
    assert universal.execution_contract_for(
        AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
    ) is AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1
    assert universal.planning_contract_for(
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        planned=True,
    ) is AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2
    assert universal.planning_contract_for(
        planning_mode=AgentPlanningMode.STANDARD,
        planned=False,
    ) is None


def test_standard_universal_preview_freezes_marker_snapshot_and_skeleton(tmp_path, monkeypatch) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(goal="Analyze this product", deliverables=["analysis_result"])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    universal_search = UniversalSkillSearchService(
        repository,
        catalog,
        profile_trust=trust,
        profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
    )
    original_search = universal_search.search

    def search_with_blocked_match(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        result = original_search(*args, **kwargs)
        blocked = result.selectable_candidates[0].model_copy(
            update={
                "skill_id": "skill_blocked_preview",
                "skill_name": "blocked-preview",
                "title": "Blocked Preview Skill",
                "ready": False,
                "diagnostics": ["tool_grant_missing"],
            }
        )
        return replace(result, blocked_matches=(blocked,))

    universal_search.search = search_with_blocked_match  # type: ignore[method-assign]
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=universal_search,
        universal_preview_enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    async def scenario():
        run = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_preview",
            history=[],
            client_turn_id="turn_universal_preview",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        await runtime._tasks[run.id]
        return repository.get_agent_run(run.id), repository.get_skill_plan_for_run(run.id)

    run, plan = asyncio.run(scenario())

    assert run is not None and plan is not None
    assert run.planning_contract_version is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
    assert run.execution_contract_version is AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1
    assert "execution_contract_version" in run.model_dump()
    assert run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert plan.candidate_snapshot is not None
    assert plan.execution_contract_version is AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1
    assert "execution_contract_version" in plan.model_dump()
    assert plan.candidate_skill_ids == [skill.id]
    assert plan.candidate_snapshot.candidates[0].skill_id == skill.id
    assert plan.nodes[0].resource_manifest is not None
    assert plan.version == 2
    events = repository.list_agent_run_events(run.id)
    assert [event.event_type for event in events].count("candidate_snapshot_created") == 1
    search_event = next(
        event for event in events if event.event_type == "skill_search_completed"
    )
    assert search_event.payload["blocked_matches"] == [
        {
            "skill_id": "skill_blocked_preview",
            "skill_name": "blocked-preview",
            "title": "Blocked Preview Skill",
            "reason_codes": ["tool_grant_missing"],
        }
    ]
    assert not any(event.event_type == "plan_execution_started" for event in events)

    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "catalog_service", lambda: catalog)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "preview")
    detail = agent_run_routes.get_agent_run_plan(run.id, user=USER)
    serialized = detail.model_dump_json()
    assert detail.plan.candidate_snapshot is not None
    assert [item.skill_id for item in detail.blocked_matches] == [
        "skill_blocked_preview"
    ]
    assert detail.blocked_matches[0].reason_codes == ("tool_grant_missing",)
    assert "profile_content_hash" not in serialized
    assert "evidence_path_witnesses" not in serialized
    assert "resource_manifest" not in serialized
    approved = asyncio.run(
        agent_run_routes.approve_agent_run_plan(
            run.id,
            SkillPlanVersionRequest(expected_version=plan.version),
            user=USER,
        )
    )
    assert approved.run.status is AgentRunStatus.COMPLETED
    assert approved.plan.execution_contract_version is AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1


def test_all_blocked_universal_run_projects_safe_match_diagnostics(
    tmp_path,
    monkeypatch,
) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(goal="Analyze this product", deliverables=["analysis_result"])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    universal_search = UniversalSkillSearchService(
        repository,
        catalog,
        profile_trust=trust,
        profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
    )
    baseline = universal_search.search(USER, intent)
    blocked = baseline.selectable_candidates[0].model_copy(
        update={
            "ready": False,
            "diagnostics": ["tool_grant_missing"],
        }
    )
    failed_search = replace(
        baseline,
        selectable_candidates=(),
        blocked_matches=(blocked,),
        outcome_code="no_executable_skill",
    )
    universal_search.search = lambda *_args, **_kwargs: failed_search  # type: ignore[method-assign]
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=universal_search,
        universal_preview_enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    async def scenario():
        run = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_all_blocked",
            history=[],
            client_turn_id="turn_universal_all_blocked",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        with pytest.raises(RuntimeError, match="no_executable_skill"):
            await runtime._tasks[run.id]
        return repository.get_agent_run(run.id)

    failed = asyncio.run(scenario())

    assert failed is not None and failed.status is AgentRunStatus.FAILED
    assert failed.error_code == "no_executable_skill"
    assert "Universal Preview Skill" in (failed.output_text or "")
    assert "tool_grant_missing" in (failed.output_text or "")


def test_routed_universal_preview_accepts_server_owned_scenario_assignment(tmp_path, monkeypatch) -> None:
    output_kinds = [
        "competitive_analysis",
        "risk_analysis",
        "design_strategy",
        "category_opportunities",
    ]
    repository, catalog, skill = _catalog(tmp_path, output_kinds=output_kinds)
    intent = SkillIntent(
        goal="对比淘宝和拼多多的竞品体验",
        deliverables=["competitive_analysis"],
    )

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=trust,
            profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        ),
        universal_preview_enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")

    async def scenario():
        run = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_routed_preview",
            history=[],
            client_turn_id="turn_universal_routed_preview",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        task = runtime._tasks.get(run.id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        return repository.get_agent_run(run.id), repository.get_skill_plan_for_run(run.id)

    run, plan = asyncio.run(scenario())

    assert run is not None and run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert plan is not None
    assert plan.nodes[0].scenario_id == "competitor-benchmark-research"
    assert plan.nodes[0].task_id == "find-direction"
    assert plan.nodes[0].skill_registry_id is None
    assert plan.nodes[0].skill_status is None


def test_universal_retry_replans_with_a_new_snapshot_backed_plan(tmp_path, monkeypatch) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(goal="Analyze this product", deliverables=["analysis_result"])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=trust,
            profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        ),
        universal_preview_enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    async def scenario():
        original = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_retry",
            history=[],
            client_turn_id="turn_universal_retry_original",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        await runtime._tasks[original.id]
        original = repository.get_agent_run(original.id)
        original_plan = repository.get_skill_plan_for_run(original.id)
        assert original is not None and original_plan is not None
        repository.save_agent_run(original.model_copy(update={"status": AgentRunStatus.CANCELLED}))
        retried = await runtime.retry_orchestrated(
            prior_run=original.model_copy(update={"status": AgentRunStatus.CANCELLED}),
            prior_plan=original_plan,
            user=USER,
            client_turn_id="turn_universal_retry_new",
            mode=SkillOrchestrationMode.PREVIEW,
            history=[],
        )
        await runtime._tasks[retried.id]
        return retried, repository.get_skill_plan_for_run(retried.id)

    retried, retried_plan = asyncio.run(scenario())

    assert retried.retry_of_run_id is not None
    assert retried.planning_contract_version is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
    assert retried_plan is not None
    assert retried_plan.run_id == retried.id
    assert retried_plan.candidate_snapshot is not None
    assert retried_plan.candidate_skill_ids == [skill.id]


def test_universal_planner_timeout_fails_the_persisted_skeleton(tmp_path, monkeypatch) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(
        goal="Analyze this product",
        deliverables=["analysis_result"],
        complexity=SkillIntentComplexity.ASSISTED,
    )

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class SlowPlanner:
        async def create_universal_draft(self, *_args, **_kwargs):
            await asyncio.sleep(10)
            raise AssertionError("timeout did not cancel the Planner")

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        skill_planner=SlowPlanner(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=trust,
            profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        ),
        universal_preview_enabled=True,
    )
    monkeypatch.setattr(runtime, "_remaining_run_seconds", lambda _run: 0.001)
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    async def scenario():
        run = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_timeout",
            history=[],
            client_turn_id="turn_universal_timeout",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        task = runtime._tasks.get(run.id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        return repository.get_agent_run(run.id), repository.get_skill_plan_for_run(run.id)

    run, plan = asyncio.run(scenario())

    assert run is not None and run.status is AgentRunStatus.FAILED
    assert run.error_code == "planner_timeout"
    assert plan is not None and plan.status.value == "failed"
    assert plan.candidate_snapshot is not None


def test_universal_retrieval_failure_terminates_run_without_empty_plan(tmp_path, monkeypatch) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(goal="Invent an unsupported artifact", deliverables=["unknown_output"])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=trust,
            profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        ),
        universal_preview_enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    async def scenario():
        run = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_unsupported",
            history=[],
            client_turn_id="turn_universal_unsupported",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        task = runtime._tasks.get(run.id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        return repository.get_agent_run(run.id)

    run = asyncio.run(scenario())

    assert run is not None
    assert run.status is AgentRunStatus.FAILED
    assert run.error_code == "unsupported_requirement"
    assert run.plan_id is None
    assert repository.get_skill_plan_for_run(run.id) is None


def test_phase2b_executes_a_frozen_read_only_universal_plan(tmp_path, monkeypatch) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(goal="Analyze this product", deliverables=["analysis_result"])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    class Synthesis:
        async def synthesize(self, **_kwargs):
            return SkillSynthesisResult(summary="Completed analysis"), False

    trust = Trust()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=trust,
            profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        ),
        universal_preview_enabled=True,
    )
    runtime.synthesis_service = Synthesis()  # type: ignore[assignment]
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")

    async def fake_node(*, plan, node, **kwargs):  # noqa: ANN001, ANN202
        run = kwargs["run"]
        user = kwargs["user"]
        runtime._resolve_plan_node_security(
            plan=plan,
            node=node,
            run=run,
            user=user,
        )
        definition = repository.get_skill_definition(node.skill_id)
        assert definition is not None
        normalized = runtime._normalize_skill_node_result(
            _StandardSkillNodeResultDraft(
                node_id=node.id,
                skill_id=node.skill_id,
                summary="Complete",
                deliverable_markdown="# Analysis",
                delivered_output_kinds=list(node.output_contract),
            ),
            total_tokens=1,
            plan=plan,
            node=node,
            skill=definition,
            run=run,
            user=user,
            allowed_source_ids=set(),
            allowed_artifact_ids=set(),
            allowed_resource_references=set(),
            upstream_source_origins={},
            runtime_context=AgentMeshRunContext(
                user_id=run.user_id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                thread_id=run.thread_id,
                run_id=run.id,
                plan_id=plan.id,
                node_id=node.id,
                skill_id=node.skill_id,
            ),
        )
        return NodeExecutionOutcome(result=normalized)

    runtime._execute_skill_plan_node = fake_node  # type: ignore[method-assign]

    async def scenario():
        created = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_execute",
            history=[],
            client_turn_id="turn_universal_execute",
            mode=SkillOrchestrationMode.EXECUTE,
        )
        await runtime._tasks[created.id]
        waiting_run = repository.get_agent_run(created.id)
        plan = repository.get_skill_plan_for_run(created.id)
        assert waiting_run is not None and plan is not None
        monkeypatch.setattr(agent_run_routes, "store", repository)
        monkeypatch.setattr(agent_run_routes, "catalog_service", lambda: catalog)
        monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
        transition = await agent_run_routes.approve_agent_run_plan(
            created.id,
            SkillPlanVersionRequest(expected_version=plan.version),
            user=USER,
        )
        assert transition.run.status is AgentRunStatus.RUNNING
        await runtime._tasks[created.id]
        return repository.get_agent_run(created.id), repository.get_skill_plan_for_run(created.id)

    run, plan = asyncio.run(scenario())

    assert run is not None and run.status is AgentRunStatus.COMPLETED
    assert run.error_code is None
    assert plan is not None and plan.status.value == "completed"
    assert plan.completion_check is not None and plan.completion_check.completed is True
    planning_dispatch = repository.get_run_dispatch(
        runtime._dispatch_operation_key(run.id, "standard_plan")
    )
    execution_dispatch = repository.get_run_dispatch(
        runtime._dispatch_operation_key(run.id, "approved_plan")
    )
    assert planning_dispatch is not None and planning_dispatch.state.value == "settled"
    assert execution_dispatch is not None and execution_dispatch.state.value == "settled"


def test_phase2a_approve_api_rejects_persisted_universal_plan_in_execute_mode(
    tmp_path,
    monkeypatch,
) -> None:
    repository, catalog, skill = _catalog(tmp_path)
    intent = SkillIntent(goal="Analyze this product", deliverables=["analysis_result"])

    class IntentAnalyzer:
        async def analyze(self, *_args, **_kwargs):
            return intent, []

    class Trust:
        available = True

        def __call__(self, _skill, _loaded):  # noqa: ANN001, ANN204
            return True

    trust = Trust()
    monkeypatch.setattr(
        universal_execution,
        "STANDARD_UNIVERSAL_EXECUTION_CONTRACT",
        None,
    )
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzer(),  # type: ignore[arg-type]
        profile_trust=trust,  # type: ignore[arg-type]
        universal_search=UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=trust,
            profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        ),
        universal_preview_enabled=True,
    )
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    async def create_preview():
        run = await runtime.start_orchestrated(
            content=intent.goal,
            user=USER,
            thread_id="thread_universal_approval_blocked",
            history=[],
            client_turn_id="turn_universal_approval_blocked",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        await runtime._tasks[run.id]
        return repository.get_agent_run(run.id), repository.get_skill_plan_for_run(run.id)

    run, plan = asyncio.run(create_preview())
    assert run is not None and plan is not None
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "catalog_service", lambda: catalog)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setattr(
        universal_execution,
        "STANDARD_UNIVERSAL_EXECUTION_CONTRACT",
        "standard_universal_execution_v1",
    )
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")

    try:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )
    except Exception as error:
        assert getattr(error, "status_code", None) == 409
        assert getattr(error, "detail", None) == {"code": "universal_execution_not_available"}
    else:
        raise AssertionError("Phase 2A approval admitted Universal execution")
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.status is AgentRunStatus.WAITING_PLAN_APPROVAL


def test_phase2b_freezes_execution_contract_for_new_universal_runs(tmp_path) -> None:
    repository, catalog, _skill = _catalog(tmp_path)
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        universal_preview_enabled=True,
    )

    assert runtime.execution_contract_for(
        AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
    ) is AgentExecutionContractVersion.STANDARD_UNIVERSAL_V1
    assert runtime.execution_contract_for(
        AgentPlanningContractVersion.STANDARD_LEGACY_V1
    ) is None
