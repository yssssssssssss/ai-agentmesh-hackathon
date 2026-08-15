"""Autonomous collaboration market — background workers.

agent-1 (publisher): periodically publishes each user's MARKETPLACE_SIGNAL to the BBS.
Gated by a global master switch (mirrors the other worker env flags). The step function
``publish_all_signals`` is the tested unit; the asyncio loop is a thin wrapper, following
the auto-post / research-dispatch worker convention (loop untested, step tested).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from agentmesh.agents import PersonalAgent
from agentmesh.models import now_utc
from agentmesh.seed import list_users
from agentmesh.store import SQLiteStore, store

logger = logging.getLogger(__name__)


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


# Master switch for the whole autonomous market (off by default).
MARKET_ENABLED = _bool_env("AGENTMESH_MARKET_ENABLED")
# Independent brake: keep the market "enabled" for the UI (no "未启用" banner) while
# holding the background workers still — used for a frozen demo where the graph and
# timeline must not drift. Defaults to running when the market is enabled.
MARKET_WORKERS_ENABLED = MARKET_ENABLED and not _bool_env("AGENTMESH_MARKET_WORKERS_DISABLED")
MARKET_PUBLISH_INTERVAL_SECONDS = _positive_int_env("AGENTMESH_MARKET_PUBLISH_INTERVAL_SECONDS", 300)
MARKET_SCOUT_INTERVAL_SECONDS = _positive_int_env("AGENTMESH_MARKET_SCOUT_INTERVAL_SECONDS", 300)
MARKET_SCOUT_MAX_PER_RUN = _positive_int_env("AGENTMESH_MARKET_SCOUT_MAX_PER_RUN", 20)

publish_worker_task: asyncio.Task | None = None
publish_worker_state: dict[str, object] = {
    "enabled": MARKET_WORKERS_ENABLED,
    "interval_seconds": MARKET_PUBLISH_INTERVAL_SECONDS,
    "running": False,
    "last_run_at": None,
    "last_published": 0,
    "last_error": None,
}


def publish_all_signals(repository: SQLiteStore) -> int:
    """Publish a MARKETPLACE_SIGNAL for every user that has source material. Returns the count.

    This is the step function the publisher worker drives each tick; it's the tested seam.
    """
    agent = PersonalAgent(repository)
    published = 0
    for user in list_users(repository):
        if not repository.is_market_participant(user.id):
            continue
        if agent.publish_marketplace_signal(user) is not None:
            published += 1
    logger.info("market publish: %d signals published", published)
    return published


async def publish_worker_loop() -> None:
    while True:
        await asyncio.sleep(MARKET_PUBLISH_INTERVAL_SECONDS)
        publish_worker_state["last_run_at"] = now_utc().isoformat()
        try:
            published = await asyncio.to_thread(publish_all_signals, store)
            publish_worker_state["last_published"] = published
            publish_worker_state["last_error"] = None
        except Exception as error:  # pragma: no cover - defensive worker boundary
            publish_worker_state["last_error"] = str(error)


async def start_market_publish_worker() -> None:
    global publish_worker_task
    if MARKET_WORKERS_ENABLED and (publish_worker_task is None or publish_worker_task.done()):
        publish_worker_task = asyncio.create_task(publish_worker_loop())
        publish_worker_state["running"] = True


async def stop_market_publish_worker() -> None:
    global publish_worker_task
    if publish_worker_task is not None:
        publish_worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await publish_worker_task
        publish_worker_task = None
    publish_worker_state["running"] = False


# --- agent-2: scout ---

scout_worker_task: asyncio.Task | None = None
scout_worker_state: dict[str, object] = {
    "enabled": MARKET_WORKERS_ENABLED,
    "interval_seconds": MARKET_SCOUT_INTERVAL_SECONDS,
    "running": False,
    "last_run_at": None,
    "last_triggered": 0,
    "last_error": None,
}


# Persistent per-helper fingerprint sets so the scout doesn't re-evaluate unchanged needs
# every tick (cost control). In-memory: resets on restart (one re-scan after restart is fine).
_scout_seen: dict[str, set[str]] = {}


def reset_scout_state() -> None:
    """Clear the scout dedup cache (used when the underlying store is reset)."""
    _scout_seen.clear()


def scout_all(repository: SQLiteStore) -> int:
    """Run every user's scout; return the total number of delegated answers triggered.

    This is the step function the scout worker drives each tick; it's the tested seam.
    Dedups unchanged needs across ticks and caps matches per helper per run.
    """
    agent = PersonalAgent(repository)
    triggered = 0
    for user in list_users(repository):
        if not repository.is_market_participant(user.id):
            continue
        seen = _scout_seen.setdefault(user.id, set())
        triggered += len(agent.scout_and_match(user, seen=seen, max_matches=MARKET_SCOUT_MAX_PER_RUN))
    logger.info("market scout: %d answers triggered", triggered)
    return triggered


async def scout_worker_loop() -> None:
    while True:
        await asyncio.sleep(MARKET_SCOUT_INTERVAL_SECONDS)
        scout_worker_state["last_run_at"] = now_utc().isoformat()
        try:
            triggered = await asyncio.to_thread(scout_all, store)
            scout_worker_state["last_triggered"] = triggered
            scout_worker_state["last_error"] = None
        except Exception as error:  # pragma: no cover - defensive worker boundary
            scout_worker_state["last_error"] = str(error)


async def start_market_scout_worker() -> None:
    global scout_worker_task
    if MARKET_WORKERS_ENABLED and (scout_worker_task is None or scout_worker_task.done()):
        scout_worker_task = asyncio.create_task(scout_worker_loop())
        scout_worker_state["running"] = True


async def stop_market_scout_worker() -> None:
    global scout_worker_task
    if scout_worker_task is not None:
        scout_worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scout_worker_task
        scout_worker_task = None
    scout_worker_state["running"] = False
