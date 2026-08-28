"""Provider health check routes."""

from __future__ import annotations

import os
import shutil
from math import ceil

import agents as openai_agents
from fastapi import APIRouter, Depends, Request

from agentmesh.agent_runtime.settings import (
    agent_runtime_enabled,
    skill_orchestration_mode,
)
from agentmesh.datasources import data_api_provider_status, default_data_source_registry
from agentmesh.deepsearch.admission import deepsearch_admission_rejections
from agentmesh.documents import CompositeDocumentParser
from agentmesh.embedding import embedding_provider_status
from agentmesh.llm import llm_provider_status, llm_timeout_config, model_config_from_env
from agentmesh.models import AgentPlanningMode, AgentRunStatus, ProviderHealthCheckResponse, User
from agentmesh.o2 import O2CommandRunner, maybe_register_o2_data_connector, o2_research_provider_status
from agentmesh.permissions import ACTION_VIEW_PROVIDER_HEALTH
from agentmesh.provider_status import ProviderStatus, build_provider_status
from agentmesh.routes.deps import require_permission
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store
from agentmesh.web_research import web_research_provider_status

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


def _status_payload(status: ProviderStatus, *, name: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = status.model_dump(mode="json")
    payload["name"] = name or status.name
    if not status.configured:
        payload["status"] = "not_configured"
    elif status.ready:
        payload["status"] = "ready"
    else:
        payload["status"] = "degraded"
    return payload


def _embedding_status() -> dict[str, object]:
    return _status_payload(embedding_provider_status())


def _llm_status() -> dict[str, object]:
    status = llm_provider_status()
    payload = _status_payload(status)
    config = model_config_from_env("default")
    if config is not None:
        payload.update(
            {
                "status": "configured",
                "model": config["model_name"],
                "label": config.get("label", ""),
                "api_style": config.get("api_style", "chat_completions"),
                "timeouts": llm_timeout_config(),
            }
        )
    return payload


def _web_provider_status() -> dict[str, object]:
    status = web_research_provider_status()
    payload = _status_payload(status)
    provider_type = os.getenv("AGENTMESH_WEB_PROVIDER", "").strip().lower()
    if provider_type:
        payload["provider_type"] = provider_type
    if provider_type == "tavily" and os.getenv("AGENTMESH_FIRECRAWL_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        payload["content_provider"] = "firecrawl"
    if status.configured and not status.ready:
        payload["status"] = "command_not_found" if provider_type in {"opencli", "agent_browser"} else "degraded"
    return payload


def _o2_status() -> dict[str, object]:
    runner = O2CommandRunner()
    status = o2_research_provider_status(runner)
    payload = _status_payload(status, name="o2")
    research_enabled = os.getenv("AGENTMESH_O2_RESEARCH_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    data_enabled = os.getenv("AGENTMESH_O2_DATA_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    payload.update(
        {
            "status": "installed" if runner.available() else "not_installed",
            "research_enabled": research_enabled,
            "data_enabled": data_enabled,
            "research_cli": os.getenv("AGENTMESH_O2_RESEARCH_CLI", "metasearch") if research_enabled else None,
            "data_cli": os.getenv("AGENTMESH_O2_DATA_CLI", "metasearch") if data_enabled else None,
        }
    )
    return payload


def _data_connectors_status() -> dict[str, object]:
    data_api_status = data_api_provider_status()
    registry = default_data_source_registry()
    maybe_register_o2_data_connector(registry)
    connectors = registry.list_connectors()
    status = ProviderStatus(
        name="data_connectors",
        configured=bool(connectors),
        ready=bool(connectors),
        mode="real" if data_api_status.ready else "fallback",
        last_error=data_api_status.last_error,
        latency_ms=data_api_status.latency_ms,
    )
    payload = _status_payload(status)
    payload.update({"status": "ready" if connectors else "empty", "count": len(connectors), "connectors": connectors})
    return payload


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, ceil(len(ordered) * 0.95) - 1)], 3)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _orchestration_metrics(runs) -> dict[str, object]:  # noqa: ANN001
    plan_status_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    waiting_plan_ids: set[str] = set()
    modified_plan_ids: set[str] = set()
    candidate_latencies: list[float] = []
    node_durations: list[float] = []
    approval_latencies: list[float] = []
    preview_latencies: list[float] = []
    three_node_run_durations: list[float] = []
    total_tokens = 0
    results_total = 0
    results_with_sources = 0

    for run in runs:
        plan = store.get_skill_plan_for_run(run.id)
        if plan is None:
            continue
        plan_status_counts[plan.status.value] = plan_status_counts.get(plan.status.value, 0) + 1
        for node in plan.nodes:
            if node.started_at is not None and node.completed_at is not None:
                node_durations.append((node.completed_at - node.started_at).total_seconds() * 1000)
        results = store.list_skill_node_results(plan.id)
        results_total += len(results)
        results_with_sources += sum(bool(result.sources) for result in results)
        total_tokens += sum(result.usage.total_tokens for result in results)

        approval_requested_at = None
        plan_approved_at = None
        execution_started_at = None
        terminal_at = None
        for event in store.list_agent_run_events(run.id):
            event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
            if event.event_type == "plan_waiting_approval":
                waiting_plan_ids.add(plan.id)
            elif event.event_type == "plan_updated":
                modified_plan_ids.add(plan.id)

            if event.event_type == "plan_approved" and plan_approved_at is None:
                plan_approved_at = event.created_at
            elif event.event_type == "plan_execution_started" and execution_started_at is None:
                execution_started_at = event.created_at
            elif event.event_type in {"run_completed", "run_partial", "run_failed", "run_cancelled"}:
                terminal_at = terminal_at or event.created_at

            if event.event_type == "skill_candidates_ranked":
                latency = event.payload.get("latency_ms")
                if isinstance(latency, int | float) and latency >= 0:
                    candidate_latencies.append(float(latency))
            elif event.event_type == "plan_created":
                preview_latencies.append((event.created_at - run.created_at).total_seconds() * 1000)
            elif event.event_type == "approval_requested":
                approval_requested_at = event.created_at
            elif event.event_type == "approval_resolved" and approval_requested_at is not None:
                approval_latencies.append((event.created_at - approval_requested_at).total_seconds() * 1000)
                approval_requested_at = None

        execution_start = execution_started_at or plan_approved_at
        if (
            len(plan.nodes) >= 3
            and run.orchestration_mode == "execute"
            and execution_start is not None
            and terminal_at is not None
            and terminal_at >= execution_start
        ):
            three_node_run_durations.append((terminal_at - execution_start).total_seconds() * 1000)

    plans_waiting = event_counts.get("plan_waiting_approval", 0)
    plans_approved = event_counts.get("plan_approved", 0)
    nodes_completed = event_counts.get("node_completed", 0)
    nodes_failed = event_counts.get("node_failed", 0)
    return {
        "plans": sum(plan_status_counts.values()),
        "plan_status_counts": plan_status_counts,
        "plan_acceptance_rate": _ratio(plans_approved, plans_waiting),
        "plan_modification_rate": _ratio(
            len(modified_plan_ids & waiting_plan_ids),
            len(waiting_plan_ids),
        ),
        "node_success_rate": _ratio(nodes_completed, nodes_completed + nodes_failed),
        "node_retries": event_counts.get("node_retry_scheduled", 0),
        "node_duration_p95_ms": _p95(node_durations),
        "approval_latency_p95_ms": _p95(approval_latencies),
        "candidate_retrieval_p95_ms": _p95(candidate_latencies),
        "plan_preview_p95_ms": _p95(preview_latencies),
        "three_node_run_p95_ms": _p95(three_node_run_durations),
        "total_tokens": total_tokens,
        "cost": None,
        "source_coverage_rate": _ratio(results_with_sources, results_total),
    }


def _stable_metric_code(value: object) -> str:
    candidate = str(value).split(":", 1)[0]
    if candidate and len(candidate) <= 80 and all(
        character.islower() or character.isdigit() or character == "_"
        for character in candidate
    ):
        return candidate
    return "other"


def _deepsearch_metrics(runs) -> dict[str, object]:  # noqa: ANN001
    deepsearch_runs = [
        run
        for run in runs
        if getattr(run, "planning_mode", AgentPlanningMode.STANDARD)
        is AgentPlanningMode.DEEPSEARCH
    ]
    terminal_status_counts: dict[str, int] = {}
    clarification_round_counts: dict[str, int] = {}
    capability_gap_counts: dict[str, int] = {}
    review_verdict_counts: dict[str, int] = {}
    stage_durations: list[float] = []
    end_to_end_durations: list[float] = []
    evidence_checked = 0
    evidence_passed = 0
    review_checked_runs = 0
    revised_runs = 0
    clarification_exhausted = 0
    planning_failed = 0

    terminal_statuses = {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.PARTIAL,
        AgentRunStatus.FAILED,
        AgentRunStatus.REJECTED,
        AgentRunStatus.CANCELLED,
    }
    for run in deepsearch_runs:
        if run.status in terminal_statuses:
            terminal_status_counts[run.status.value] = (
                terminal_status_counts.get(run.status.value, 0) + 1
            )
            end_to_end_durations.append(
                max(0.0, (run.updated_at - run.created_at).total_seconds() * 1000)
            )
        if run.error_code == "deepsearch_clarification_unresolved":
            clarification_exhausted += 1
        if run.error_code in {
            "deepsearch_planning_failed",
            "deepsearch_planning_transient",
        }:
            planning_failed += 1

        plan = store.get_skill_plan_for_run(run.id)
        if plan is not None:
            for gap in plan.capability_gaps:
                code = _stable_metric_code(gap)
                capability_gap_counts[code] = capability_gap_counts.get(code, 0) + 1
            if plan.evidence_coverage is not None:
                evidence_checked += 1
                evidence_passed += int(plan.evidence_coverage.passed)
            if plan.review_outcomes:
                review_checked_runs += 1
                revised_runs += int(len(plan.review_outcomes) > 1)
                for outcome in plan.review_outcomes:
                    review_verdict_counts[outcome.outcome] = (
                        review_verdict_counts.get(outcome.outcome, 0) + 1
                    )

        previous_stage_at = None
        for event in store.list_agent_run_events(run.id):
            if event.event_type == "deepsearch_clarification_requested":
                round_number = event.payload.get("clarification_round")
                if type(round_number) is int and 1 <= round_number <= 3:
                    key = str(round_number)
                    clarification_round_counts[key] = (
                        clarification_round_counts.get(key, 0) + 1
                    )
            if event.event_type == "deepsearch_finalization_stage_changed":
                if previous_stage_at is not None:
                    stage_durations.append(
                        max(0.0, (event.created_at - previous_stage_at).total_seconds() * 1000)
                    )
                previous_stage_at = event.created_at

    terminal_count = sum(terminal_status_counts.values())
    partial_or_failed = terminal_status_counts.get("partial", 0) + terminal_status_counts.get(
        "failed", 0
    )
    return {
        "runs_started": len(deepsearch_runs),
        "terminal_status_counts": terminal_status_counts,
        "clarification_round_counts": clarification_round_counts,
        "clarification_exhaustion_rate": _ratio(
            clarification_exhausted,
            len(deepsearch_runs),
        ),
        "planning_failure_rate": _ratio(planning_failed, len(deepsearch_runs)),
        "capability_gap_counts": capability_gap_counts,
        "evidence_pass_rate": _ratio(evidence_passed, evidence_checked),
        "review_verdict_counts": review_verdict_counts,
        "review_revision_rate": _ratio(revised_runs, review_checked_runs),
        "partial_failed_rate": _ratio(partial_or_failed, terminal_count),
        "stage_duration_p95_ms": _p95(stage_durations),
        "end_to_end_p95_ms": _p95(end_to_end_durations),
        "admission_rejected_by_code": deepsearch_admission_rejections(),
        "admission_window": "process_lifetime",
    }


def _agent_runtime_status(*, deepsearch_recovery_running: bool = False) -> dict[str, object]:
    runtime_enabled = agent_runtime_enabled()
    runs = store.list_agent_runs()
    status_counts: dict[str, int] = {}
    for run in runs:
        status_counts[run.status.value] = status_counts.get(run.status.value, 0) + 1
    config = model_config_from_env("default")
    configured = config is not None
    compatible = bool(config and config["api_style"] == "chat_completions")
    ready = runtime_enabled and configured and compatible
    catalog = catalog_service()
    planner_profiles = [profile for profile in store.skill_capability_profiles if profile.planner_eligible]
    profile_errors = sum(item.level == "error" for item in catalog.diagnostics)
    profile_ready = bool(planner_profiles) and profile_errors == 0
    index_counts = store.skill_search_index_counts()
    index_ready = index_counts["records"] == index_counts["indexed"] and index_counts["missing"] == 0
    orchestration_mode = skill_orchestration_mode()
    runtime_status = (
        "ready"
        if ready
        else "disabled"
        if not runtime_enabled
        else "model_not_configured"
        if not configured
        else "unsupported_api_style"
    )
    return {
        "name": "openai_agents_sdk",
        "status": runtime_status,
        "configured": configured,
        "ready": ready,
        "mode": "real" if ready else "fallback",
        "sdk_version": getattr(openai_agents, "__version__", "unknown"),
        "runtime_enabled": runtime_enabled,
        "skill_orchestration_mode": orchestration_mode.value,
        "deepsearch_recovery_running": deepsearch_recovery_running,
        "skills": len(catalog.list_enabled()),
        "planner_profiles": len(planner_profiles),
        "profile_health": "ready" if profile_ready else "degraded",
        "profile_errors": profile_errors,
        "index_health": "ready" if index_ready else "degraded",
        "index_counts": index_counts,
        "planner_health": (
            "disabled"
            if orchestration_mode.value == "off"
            else "ready"
            if ready and profile_ready and index_ready
            else "degraded"
        ),
        "runs": len(runs),
        "run_status_counts": status_counts,
        "orchestration_metrics": _orchestration_metrics(runs),
        "deepsearch_metrics": _deepsearch_metrics(runs),
        "skill_activations": sum(event.action == "sdk_skill_activated" for event in store.audit_events),
        "open_tool_approvals": sum(
            item.item_type == "sdk_tool_approval" and item.status == "open" for item in store.inbox_items
        ),
    }


def _document_parser_status() -> dict[str, object]:
    parser = CompositeDocumentParser()
    supported = sorted(parser.supported_extensions)
    try:
        import fitz  # noqa: F401

        pdf_available = True
    except ImportError:
        pdf_available = False
    ocr_available = shutil.which(os.getenv("AGENTMESH_TESSERACT_COMMAND", "tesseract")) is not None
    payload = _status_payload(
        build_provider_status(
            name="document_parser",
            configured=True,
            ready=True,
            mode="real",
        )
    )
    payload.update(
        {
            "supported_extensions": supported,
            "pdf_available": pdf_available,
            "word_available": True,
            "slide_available": True,
            "ocr_available": ocr_available,
            "message": "支持 UTF-8 文本、Markdown、PDF、Word、PPT 和图片 OCR。",
        }
    )
    return payload


def _provider_health_snapshot(
    *,
    deepsearch_recovery_running: bool = False,
) -> ProviderHealthCheckResponse:
    providers = [
        _embedding_status(),
        _o2_status(),
        _web_provider_status(),
        _data_connectors_status(),
        _llm_status(),
        _agent_runtime_status(
            deepsearch_recovery_running=deepsearch_recovery_running
        ),
        _document_parser_status(),
    ]
    all_ready = all(bool(item["ready"]) for item in providers)
    return ProviderHealthCheckResponse(
        overall="healthy" if all_ready else "degraded",
        providers=providers,
    )


@router.get("/providers", response_model=ProviderHealthCheckResponse)
def provider_health_check(
    request: Request,
    _: User = Depends(require_permission(ACTION_VIEW_PROVIDER_HEALTH)),
) -> ProviderHealthCheckResponse:
    """Return secret-safe provider readiness for authenticated users."""

    coordinator = getattr(request.app.state, "deepsearch_recovery_coordinator", None)
    recovery_running = bool(coordinator is not None and coordinator.running)
    return _provider_health_snapshot(
        deepsearch_recovery_running=recovery_running,
    )
