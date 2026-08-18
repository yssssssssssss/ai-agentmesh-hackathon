"""Provider health check routes."""

from __future__ import annotations

import os
import shutil

import agents as openai_agents
from fastapi import APIRouter, Depends

from agentmesh.datasources import data_api_provider_status, default_data_source_registry
from agentmesh.documents import CompositeDocumentParser
from agentmesh.embedding import embedding_provider_status
from agentmesh.llm import llm_provider_status, llm_timeout_config, model_config_from_env
from agentmesh.models import ProviderHealthCheckResponse, User
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


def _agent_runtime_status() -> dict[str, object]:
    runtime_enabled = os.getenv("AGENTMESH_AGENT_RUNTIME", "legacy").strip().lower() == "v2"
    runs = store.list_agent_runs()
    status_counts: dict[str, int] = {}
    for run in runs:
        status_counts[run.status.value] = status_counts.get(run.status.value, 0) + 1
    config = model_config_from_env("default")
    configured = config is not None
    compatible = bool(config and config["api_style"] == "chat_completions")
    ready = runtime_enabled and configured and compatible
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
        "skills": len(catalog_service().list_enabled()),
        "runs": len(runs),
        "run_status_counts": status_counts,
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


@router.get("/providers", response_model=ProviderHealthCheckResponse)
def provider_health_check(
    _: User = Depends(require_permission(ACTION_VIEW_PROVIDER_HEALTH)),
) -> ProviderHealthCheckResponse:
    """Return secret-safe provider readiness for authenticated users."""

    providers = [
        _embedding_status(),
        _o2_status(),
        _web_provider_status(),
        _data_connectors_status(),
        _llm_status(),
        _agent_runtime_status(),
        _document_parser_status(),
    ]
    all_ready = all(bool(item["ready"]) for item in providers)
    return ProviderHealthCheckResponse(
        overall="healthy" if all_ready else "degraded",
        providers=providers,
    )
