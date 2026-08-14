"""AgentMesh FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agentmesh.marketplace import (
    start_market_publish_worker,
    start_market_scout_worker,
    stop_market_publish_worker,
    stop_market_scout_worker,
)
from agentmesh.model_registry import ensure_model_seed_data
from agentmesh.permissions import ensure_permission_policy_seed_data
from agentmesh.risk import ensure_risk_policy_seed_data
from agentmesh.routes.agents import router as agents_router
from agentmesh.routes.auth import router as auth_router
from agentmesh.routes.blackboard import router as blackboard_router
from agentmesh.routes.blackboard import (
    start_auto_post_worker,
    start_research_dispatch_worker,
    stop_auto_post_worker,
    stop_research_dispatch_worker,
)
from agentmesh.routes.chat import router as chat_router
from agentmesh.routes.data_sources import router as data_sources_router
from agentmesh.routes.documents import router as documents_router
from agentmesh.routes.health import router as health_router
from agentmesh.routes.inbox import router as inbox_router
from agentmesh.routes.market import router as market_router
from agentmesh.routes.memory import router as memory_router
from agentmesh.routes.memory import start_daily_memory_worker, stop_daily_memory_worker
from agentmesh.routes.risk import router as risk_router
from agentmesh.routes.users import router as users_router
from agentmesh.routes.workspace import router as workspace_router
from agentmesh.seed import ensure_demo_data, ensure_graph_demo_data, ensure_initial_blackboard_data, ensure_seed_data
from agentmesh.store import store
from agentmesh.tools import ensure_tool_seed_data

ROOT_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_auto_post_worker()
    await start_daily_memory_worker()
    await start_research_dispatch_worker()
    await start_market_publish_worker()
    await start_market_scout_worker()
    yield
    await stop_market_scout_worker()
    await stop_market_publish_worker()
    await stop_research_dispatch_worker()
    await stop_daily_memory_worker()
    await stop_auto_post_worker()


app = FastAPI(title="AgentMesh", version="0.1.0", lifespan=lifespan)

# 初始化种子数据
ensure_seed_data(store)
ensure_initial_blackboard_data(store)
ensure_demo_data(store)
ensure_graph_demo_data(store)
ensure_tool_seed_data(store, granted_by="system")
ensure_model_seed_data(store)
ensure_risk_policy_seed_data(store)
ensure_permission_policy_seed_data(store)

# 注册路由模块
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(blackboard_router)
app.include_router(memory_router)
app.include_router(inbox_router)
app.include_router(market_router)
app.include_router(documents_router)
app.include_router(data_sources_router)
app.include_router(risk_router)
app.include_router(workspace_router)
app.include_router(health_router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "app.html")


@app.get("/app.html")
def app_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "app.html")


static_dir = ROOT_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
