from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.artifacts import V1VerifiedArtifactStore
from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    ChatThread,
    DeepSearchBudgetV1,
    DeepSearchFinalizationStage,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanStatus,
    SkillSynthesisResult,
)
from agentmesh.report_html import render_report_html
from agentmesh.seed import TEAM_LEAD, USER
from agentmesh.store import store


def _login(client: TestClient, user_id: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert response.status_code == 200


def _save_standard_report() -> AgentRun:
    markdown = """# 企业 AI 助手研究报告

## 竞品矩阵

| 产品 | 主要能力 | 风险 |
| --- | --- | --- |
| 产品 A | 证据追溯 | 权限边界 |

## 招募问卷

1. 你的主要职责是什么？
2. 每周使用生成式 AI 的频率是多少？
"""
    run = store.save_agent_run(
        AgentRun(
            id="run_html_report_standard",
            thread_id="thread_html_report_standard",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="为企业设计团队制定完整用户研究方案",
            status=AgentRunStatus.COMPLETED,
            output_text=markdown,
        )
    )
    synthesis = SkillSynthesisResult(summary="完整用户研究方案")
    plan = store.save_skill_plan(
        SkillPlan(
            id="plan_html_report_standard",
            run_id=run.id,
            status=SkillPlanStatus.COMPLETED,
            intent=SkillIntent(goal=run.input_text, deliverables=["report"]),
            output_contract=["report"],
            synthesis=synthesis.model_dump(mode="json"),
        )
    )
    return store.save_agent_run(run.model_copy(update={"plan_id": plan.id}))


def _save_deepsearch_report(suffix: str) -> tuple[AgentRun, Artifact]:
    created_at = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    run_id = f"run_html_report_deepsearch_{suffix}"
    plan_id = f"plan_html_report_deepsearch_{suffix}"
    requirement_id = f"requirement_html_report_deepsearch_{suffix}"
    artifact_id = f"artifact_html_report_deepsearch_{suffix}"
    markdown = """# DeepSearch 用户研究报告

## 访谈样本

| 角色 | 人数 |
| --- | ---: |
| 设计师 | 8 |
"""
    store.add_chat_thread(
        ChatThread(
            id=f"thread_html_report_deepsearch_{suffix}",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            title="DeepSearch HTML report",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    initial_run, created = store.claim_new_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_html_report_deepsearch_{suffix}",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="生成用户研究报告",
            client_turn_id=f"turn_html_report_deepsearch_{suffix}",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            absolute_expires_at=created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert created

    report_payload = {
        "schema_version": "deepsearch-report-v1",
        "run_id": run_id,
        "requirement_version_id": requirement_id,
        "plan_id": plan_id,
        "plan_version": 1,
        "requirement_content_hash": "1" * 64,
        "problem_graph_hash": "2" * 64,
        "plan_content_hash": "3" * 64,
        "evidence_manifest_hash": "4" * 64,
        "synthesis_content_hash": "5" * 64,
        "review_outcome": "pass",
        "review_reason_code": None,
        "report_status": "complete",
        "title": "DeepSearch 用户研究报告",
        "claims": [],
        "executive_summary_claim_ids": [],
        "sections": [],
        "sources": [],
        "limitations": [],
        "rendered_text": markdown,
    }
    content = canonical_json_bytes(report_payload).decode("utf-8")
    content_bytes = content.encode("utf-8")
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    staging = Artifact(
        id=artifact_id,
        run_id=run_id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        user_id=USER.id,
        artifact_type="deepsearch_report",
        content_type="application/json",
        content="",
        verification_state=ArtifactVerificationState.STAGING,
        schema_version="deepsearch-report-v1",
        requirement_version_id=requirement_id,
        plan_version_id=f"{plan_id}:v1",
        created_at=created_at,
        updated_at=created_at,
    )
    sealed = staging.model_copy(
        update={
            "content": content,
            "verification_state": ArtifactVerificationState.SEALED,
            "content_hash": content_hash,
            "size_bytes": len(content_bytes),
        }
    )
    writer = V1VerifiedArtifactStore(store)
    writer.create_staging_report(staging)
    writer.seal_report(sealed)

    plan = SkillPlan(
        id=plan_id,
        run_id=run_id,
        status=SkillPlanStatus.COMPLETED,
        intent=SkillIntent(goal=initial_run.input_text, deliverables=["report"]),
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=requirement_id,
        requirement_content_hash=report_payload["requirement_content_hash"],
        problem_graph_hash=report_payload["problem_graph_hash"],
        plan_content_hash=report_payload["plan_content_hash"],
        report_artifact_id=artifact_id,
        report_content_hash=content_hash,
        finalization_stage=DeepSearchFinalizationStage.TERMINAL_COMMITTED,
        finalization_version=1,
        created_at=created_at,
        updated_at=created_at,
    )
    run = initial_run.model_copy(
        update={
            "plan_id": plan_id,
            "status": AgentRunStatus.COMPLETED,
            "output_text": markdown,
            "updated_at": created_at,
        }
    )
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        store._write_skill_plan(connection, plan)
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )
    return run, sealed


def _corrupt_deepsearch_artifact(artifact: Artifact, corruption: str) -> None:
    payload = artifact.model_dump(mode="json")
    indexed_column: str
    indexed_value: str
    if corruption == "hash":
        indexed_column = "content_hash"
        indexed_value = "0" * 64
    elif corruption == "schema":
        indexed_column = "schema_version"
        indexed_value = "deepsearch-report-v999"
    else:
        indexed_column = "plan_version_id"
        indexed_value = "plan_unrelated:v1"
    payload[indexed_column] = indexed_value
    with store._connect() as connection:
        connection.execute(
            f"UPDATE artifacts SET payload = ?, {indexed_column} = ? WHERE id = ?",  # noqa: S608
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), indexed_value, artifact.id),
        )


def test_report_renderer_supports_tables_and_escapes_raw_html() -> None:
    document = render_report_html(
        title='研究报告 <unsafe>',
        markdown=(
            "# 研究报告\n\n"
            "| 项目 | 结论 |\n| --- | --- |\n| 访谈 | 需要执行 |\n\n"
            "<script>alert('xss')</script>\n\n"
            "[资料](https://example.com/source) [危险](javascript:alert(1))"
        ),
        status_label="完整输出",
        back_href="/workspace/thread/thread-1?run=run-1",
        download_href="/api/agent/runs/run-1/report.html?download=true",
    )

    assert document.startswith("<!doctype html>")
    assert "<table>" in document
    assert "<script>alert" not in document
    assert "&lt;script&gt;alert('xss')&lt;/script&gt;" in document
    assert 'href="javascript:' not in document
    assert 'target="_blank" rel="noopener noreferrer"' in document
    assert "研究报告 &lt;unsafe&gt;" in document
    assert "@media print" in document


def test_standard_report_route_returns_view_and_download_with_owner_scope() -> None:
    run = _save_standard_report()
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    view = client.get(f"/api/agent/runs/{run.id}/report.html")
    download = client.get(f"/api/agent/runs/{run.id}/report.html?download=true")

    assert view.status_code == 200
    assert view.headers["content-type"].startswith("text/html")
    assert view.headers["cache-control"] == "private, no-store"
    assert "script-src 'none'" in view.headers["content-security-policy"]
    assert "<table>" in view.text
    assert "竞品矩阵" in view.text
    assert "招募问卷" in view.text
    assert "返回对话" in view.text
    assert download.status_code == 200
    assert download.headers["content-disposition"] == (
        'attachment; filename="agentmesh-report-run_html_report_standard.html"'
    )
    assert "返回对话" not in download.text
    assert "<table>" in download.text

    _login(client, TEAM_LEAD.id, "lead123")
    assert client.get(f"/api/agent/runs/{run.id}/report.html").status_code == 404


@pytest.mark.parametrize("corruption", ["hash", "schema", "lineage"])
def test_deepsearch_report_route_requires_a_verified_sealed_artifact(corruption: str) -> None:
    run, artifact = _save_deepsearch_report(corruption)
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    view = client.get(f"/api/agent/runs/{run.id}/report.html")
    download = client.get(f"/api/agent/runs/{run.id}/report.html?download=true")

    assert view.status_code == 200
    assert view.headers["content-type"].startswith("text/html")
    assert "content-disposition" not in view.headers
    assert view.headers["x-agentmesh-artifact-hash"] == artifact.content_hash
    assert "DeepSearch 用户研究报告" in view.text
    assert "<table>" in view.text
    assert download.status_code == 200
    assert download.headers["content-disposition"] == (
        f'attachment; filename="agentmesh-report-{run.id}.html"'
    )
    assert download.headers["x-agentmesh-artifact-hash"] == artifact.content_hash

    _corrupt_deepsearch_artifact(artifact, corruption)

    rejected = client.get(f"/api/agent/runs/{run.id}/report.html")
    assert rejected.status_code == 409
    assert rejected.json() == {"detail": {"code": "artifact_integrity_failed"}}
    assert "DeepSearch 用户研究报告" not in rejected.text


def test_report_route_rejects_non_terminal_or_missing_synthesis() -> None:
    run = store.save_agent_run(
        AgentRun(
            id="run_html_report_unavailable",
            thread_id="thread_html_report_unavailable",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="unfinished report",
            status=AgentRunStatus.RUNNING,
            output_text="# Draft",
        )
    )
    store.save_skill_plan(
        SkillPlan(
            id="plan_html_report_unavailable",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal=run.input_text),
        )
    )
    client = TestClient(app)
    _login(client, USER.id, "designer123")

    response = client.get(f"/api/agent/runs/{run.id}/report.html")

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "report_unavailable"}}
