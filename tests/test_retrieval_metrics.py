"""Tests for R2: retrieval quality metrics."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.agents import PersonalAgent
from agentmesh.app import app
from agentmesh.models import (
    MemoryItem,
    MemoryStatus,
    RetrievalMetrics,
    Scope,
)
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.store import store


def _password() -> str:
    return "designer123"


def _authenticated_client() -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"user_id": USER.id, "password": _password()})
    assert resp.status_code == 200
    return client


class TestRetrievalMetricsModel:
    def test_metrics_stored_and_retrieved(self) -> None:
        store.reset()
        metrics = RetrievalMetrics(
            query_text="部署失败",
            user_id="user_a",
            results_returned=5,
            results_cited=2,
            source_ids_returned=["mem_1", "mem_2", "mem_3", "mem_4", "mem_5"],
            source_ids_cited=["mem_1", "mem_3"],
            latency_ms=45,
            llm_used=True,
        )
        store.add_retrieval_metrics(metrics)
        stored = store.retrieval_metrics
        assert len(stored) == 1
        assert stored[0].query_text == "部署失败"
        assert stored[0].results_returned == 5
        assert stored[0].results_cited == 2
        assert stored[0].latency_ms == 45

    def test_multiple_metrics_stored(self) -> None:
        store.reset()
        for i in range(3):
            store.add_retrieval_metrics(
                RetrievalMetrics(
                    query_text=f"查询{i}",
                    user_id="user_a",
                    results_returned=i + 1,
                )
            )
        assert len(store.retrieval_metrics) == 3


class TestRetrievalMetricsCollection:
    def setup_method(self) -> None:
        store.reset()
        store.save_project(PROJECT)
        store.save_user(USER)

    def test_metrics_collected_during_memory_search(self) -> None:
        store.add_memory_item(
            MemoryItem(
                title="团队部署规范文档",
                summary="详细的部署流程说明",
                memory_type="standard",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        agent = PersonalAgent(repository=store)
        agent._search_team_brain("部署规范", USER)
        # Metrics are recorded through _handle_memory_search, not _search_team_brain directly
        # So test via the full handle path using _ChatTurnState
        from agentmesh.agents import _ChatTurnState
        from agentmesh.models import Intent, Task, TaskStatus

        task = Task(
            thread_id="test_thread",
            intent=Intent.ASK_MEMORY,
            title="test",
            status=TaskStatus.RUNNING,
        )
        store._upsert("tasks", task)
        state = _ChatTurnState()
        agent._handle_memory_search(task, "部署规范", USER, state)
        assert state.retrieval_metrics is not None
        assert state.retrieval_metrics.results_returned >= 1
        assert state.retrieval_metrics.latency_ms >= 0
        assert state.retrieval_metrics.query_text == "部署规范"


class TestCitedSourceDetection:
    def test_finds_cited_ids_in_output(self) -> None:
        source_ids = ["mem_001", "mem_002", "mem_003"]
        llm_output = "根据 mem_001 和 mem_003 的记录，部署流程需要预先检查配置。"
        cited = PersonalAgent._find_cited_source_ids(llm_output, source_ids)
        assert "mem_001" in cited
        assert "mem_003" in cited
        assert "mem_002" not in cited

    def test_empty_output_returns_empty(self) -> None:
        assert PersonalAgent._find_cited_source_ids("", ["mem_001"]) == []

    def test_no_sources_returns_zero_count(self) -> None:
        assert PersonalAgent._count_cited_sources("some output", []) == 0


class TestRetrievalMetricsAPI:
    def setup_method(self) -> None:
        store.reset()

    def test_api_returns_empty_when_no_metrics(self) -> None:
        client = _authenticated_client()
        resp = client.get("/api/memory/retrieval-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["summary"]["total"] == 0

    def test_api_returns_metrics_with_summary(self) -> None:
        store.add_retrieval_metrics(
            RetrievalMetrics(
                query_text="测试查询",
                user_id=USER.id,
                results_returned=5,
                results_cited=2,
                latency_ms=30,
            )
        )
        store.add_retrieval_metrics(
            RetrievalMetrics(
                query_text="另一个查询",
                user_id=USER.id,
                results_returned=3,
                results_cited=1,
                latency_ms=50,
            )
        )
        client = _authenticated_client()
        resp = client.get("/api/memory/retrieval-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total"] == 2
        assert data["summary"]["total_returned"] == 8
        assert data["summary"]["total_cited"] == 3
        assert data["summary"]["avg_citation_rate"] == 0.375
        assert data["summary"]["avg_latency_ms"] == 40.0
