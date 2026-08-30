"""AgentMesh FastAPI application."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agentmesh.agent_runtime.settings import skill_orchestration_mode
from agentmesh.deepsearch.recovery import DeepSearchRecoveryCoordinator
from agentmesh.marketplace import (
    start_market_publish_worker,
    start_market_scout_worker,
    stop_market_publish_worker,
    stop_market_scout_worker,
)
from agentmesh.model_registry import ensure_model_seed_data
from agentmesh.permissions import ensure_permission_policy_seed_data
from agentmesh.request_limits import RequestBodyLimitMiddleware
from agentmesh.research_orchestration.v2_artifact_history import V2ArtifactHistoryReader
from agentmesh.research_orchestration.v2_history import V2HistoryAdapter
from agentmesh.risk import ensure_risk_policy_seed_data
from agentmesh.routes.admin_orchestration import router as admin_orchestration_router
from agentmesh.routes.agent_runs import router as agent_runs_router
from agentmesh.routes.agents import router as agents_router
from agentmesh.routes.artifacts import router as artifacts_router
from agentmesh.routes.auth import router as auth_router
from agentmesh.routes.blackboard import router as blackboard_router
from agentmesh.routes.blackboard import (
    start_auto_post_worker,
    start_research_dispatch_worker,
    stop_auto_post_worker,
    stop_research_dispatch_worker,
)
from agentmesh.routes.chat import agent as chat_agent
from agentmesh.routes.chat import router as chat_router
from agentmesh.routes.data_sources import router as data_sources_router
from agentmesh.routes.deepsearch import router as deepsearch_router
from agentmesh.routes.documents import ingestion_service
from agentmesh.routes.documents import router as documents_router
from agentmesh.routes.health import router as health_router
from agentmesh.routes.inbox import router as inbox_router
from agentmesh.routes.market import router as market_router
from agentmesh.routes.memory import router as memory_router
from agentmesh.routes.memory import start_daily_memory_worker, stop_daily_memory_worker
from agentmesh.routes.research import router as research_router
from agentmesh.routes.risk import router as risk_router
from agentmesh.routes.skills import router as skills_router
from agentmesh.routes.users import router as users_router
from agentmesh.routes.workspace import router as workspace_router
from agentmesh.runtime_admission import install_orchestration_admission
from agentmesh.runtime_capacity import RuntimeCapacityController, install_runtime_capacity
from agentmesh.seed import (
    demo_mode_enabled,
    ensure_base_workspace_data,
    ensure_demo_data,
    ensure_demo_seed_data,
    ensure_graph_demo_data,
    ensure_initial_blackboard_data,
)
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController, OrchestrationQuiescingError
from agentmesh.skill_runtime.service import ensure_skill_catalog
from agentmesh.store import SQLiteStore, store
from agentmesh.tools import ensure_tool_seed_data

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT_DIR / "agentmesh-demo" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"


def initialize_application_data(repository: SQLiteStore) -> None:
    repository.reconcile_run_dispatches_for_startup()
    repository.reconcile_orphaned_agent_runs()
    ensure_base_workspace_data(repository)
    ensure_tool_seed_data(repository, granted_by="system")
    ensure_model_seed_data(repository)
    ensure_risk_policy_seed_data(repository)
    ensure_permission_policy_seed_data(repository)
    ensure_skill_catalog(repository)
    if not demo_mode_enabled():
        return
    ensure_demo_seed_data(repository)
    ensure_initial_blackboard_data(repository)
    ensure_demo_data(repository)
    ensure_graph_demo_data(repository)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.initialize()
    initialize_application_data(store)
    research_v2_history_reader = V2HistoryAdapter(store, V2ArtifactHistoryReader(store))
    app.state.research_v2_history_reader = research_v2_history_reader
    runtime = chat_agent.agent_runtime
    orchestration_admission = install_orchestration_admission(
        OrchestrationQuiesceController()
    )
    runtime_capacity = install_runtime_capacity(RuntimeCapacityController())
    if runtime is not None:
        runtime.set_admission_controller(orchestration_admission)
        set_capacity = getattr(runtime, "set_capacity_controller", None)
        if callable(set_capacity):
            set_capacity(runtime_capacity)
        start_dispatch_pump = getattr(runtime, "start_dispatch_pump", None)
        if callable(start_dispatch_pump):
            await start_dispatch_pump()
    app.state.orchestration_quiesce_controller = orchestration_admission
    deepsearch_recovery = (
        DeepSearchRecoveryCoordinator(
            store,
            runtime,
            admission=orchestration_admission,
            mode_provider=skill_orchestration_mode,
        )
        if runtime is not None
        else None
    )
    app.state.deepsearch_recovery_coordinator = deepsearch_recovery
    if runtime is not None:
        set_recovery_wakeup = getattr(
            runtime,
            "set_deepsearch_recovery_wakeup",
            None,
        )
        if callable(set_recovery_wakeup):
            recovery_wakeup = getattr(deepsearch_recovery, "wake", None)
            set_recovery_wakeup(
                recovery_wakeup if callable(recovery_wakeup) else None
            )
    try:
        if deepsearch_recovery is not None:
            await deepsearch_recovery.start()
        await start_auto_post_worker()
        await start_daily_memory_worker()
        await start_research_dispatch_worker()
        await start_market_publish_worker()
        await start_market_scout_worker()
        yield
    finally:
        try:
            if runtime is not None:
                stop_dispatch_pump = getattr(runtime, "stop_dispatch_pump", None)
                if callable(stop_dispatch_pump):
                    await stop_dispatch_pump()
            if deepsearch_recovery is not None:
                await deepsearch_recovery.stop()
            await stop_market_scout_worker()
            await stop_market_publish_worker()
            await stop_research_dispatch_worker()
            await stop_daily_memory_worker()
            await stop_auto_post_worker()
        finally:
            if getattr(app.state, "research_v2_history_reader", None) is research_v2_history_reader:
                del app.state.research_v2_history_reader
            if (
                getattr(app.state, "deepsearch_recovery_coordinator", None)
                is deepsearch_recovery
            ):
                del app.state.deepsearch_recovery_coordinator
            if (
                getattr(app.state, "orchestration_quiesce_controller", None)
                is orchestration_admission
            ):
                del app.state.orchestration_quiesce_controller
            if runtime is not None:
                set_recovery_wakeup = getattr(
                    runtime,
                    "set_deepsearch_recovery_wakeup",
                    None,
                )
                if callable(set_recovery_wakeup):
                    set_recovery_wakeup(None)
            replacement_admission = install_orchestration_admission(
                OrchestrationQuiesceController()
            )
            replacement_capacity = install_runtime_capacity(
                RuntimeCapacityController()
            )
            if runtime is not None:
                runtime.set_admission_controller(replacement_admission)
                set_capacity = getattr(runtime, "set_capacity_controller", None)
                if callable(set_capacity):
                    set_capacity(replacement_capacity)
            await asyncio.to_thread(ingestion_service.shutdown)


app = FastAPI(title="AgentMesh", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestBodyLimitMiddleware)


@app.exception_handler(OrchestrationQuiescingError)
async def orchestration_quiescing_handler(_request, _error):  # noqa: ANN001
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": OrchestrationQuiescingError.code}},
    )


# 注册路由模块
app.include_router(auth_router)
app.include_router(admin_orchestration_router)
app.include_router(users_router)
app.include_router(agent_runs_router)
app.include_router(deepsearch_router)
app.include_router(research_router)
app.include_router(artifacts_router)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(blackboard_router)
app.include_router(memory_router)
app.include_router(inbox_router)
app.include_router(market_router)
app.include_router(documents_router)
app.include_router(data_sources_router)
app.include_router(risk_router)
app.include_router(skills_router)
app.include_router(workspace_router)
app.include_router(health_router)


def react_index() -> FileResponse:
    if not FRONTEND_INDEX.is_file():
        raise HTTPException(status_code=503, detail="React frontend is not built")
    return FileResponse(FRONTEND_INDEX)


@app.get("/", include_in_schema=False)
@app.get("/digital-self", include_in_schema=False)
@app.get("/digital-self/{spa_path:path}", include_in_schema=False)
@app.get("/digital-human", include_in_schema=False)
@app.get("/digital-human/{spa_path:path}", include_in_schema=False)
@app.get("/workspace", include_in_schema=False)
@app.get("/workspace/{spa_path:path}", include_in_schema=False)
@app.get("/insights", include_in_schema=False)
@app.get("/insights/{spa_path:path}", include_in_schema=False)
@app.get("/knowledge", include_in_schema=False)
@app.get("/knowledge/{spa_path:path}", include_in_schema=False)
@app.get("/collaboration", include_in_schema=False)
@app.get("/collaboration/{spa_path:path}", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
@app.get("/admin/{spa_path:path}", include_in_schema=False)
def react_page(spa_path: str | None = None) -> FileResponse:
    del spa_path
    return react_index()


@app.get("/app.html", include_in_schema=False)
@app.get("/legacy/app.html", include_in_schema=False)
def legacy_app_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app.html")


if FRONTEND_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS), name="react-assets")

static_dir = ROOT_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
