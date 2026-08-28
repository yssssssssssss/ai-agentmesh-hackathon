from __future__ import annotations

import asyncio
import json
from datetime import datetime

from agents.testing import ModelStep, ScriptedModel, assistant_message
from httpx import ASGITransport, AsyncClient

import agentmesh.routes.agent_runs as agent_run_routes
import agentmesh.routes.chat as chat_routes
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.routes.deps import current_user
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


def _last_user_payload(call) -> dict[str, object]:  # noqa: ANN001
    model_input = call.input
    if isinstance(model_input, str):
        content = model_input
    else:
        user_item = next(item for item in reversed(model_input) if item.get("role") == "user")
        raw_content = user_item["content"]
        if isinstance(raw_content, str):
            content = raw_content
        else:
            content = "".join(
                item["text"]
                for item in raw_content
                if item.get("type") == "input_text" and isinstance(item.get("text"), str)
            )
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload


def _assert_ordered_subsequence(actual: list[str], expected: list[str]) -> None:
    next_expected = 0
    for item in actual:
        if item == expected[next_expected]:
            next_expected += 1
            if next_expected == len(expected):
                return
    raise AssertionError(f"missing ordered events: {expected[next_expected:]}; actual events: {actual}")


def test_mainline_skill_orchestration_runs_through_http_and_sqlite(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.delenv("AGENTMESH_SKILL_PATHS", raising=False)
    monkeypatch.delenv("AGENTMESH_TRUST_PROJECT_SKILLS", raising=False)

    repository = SQLiteStore(tmp_path / "orchestration.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="test")
    catalog = SkillCatalogService(repository)
    catalog.reload()

    intent = {
        "goal": "先制定用户研究计划，再生成访谈提纲",
        "primary_stage": "pre_design",
        "input_kinds": ["design_requirement"],
        "deliverables": ["research_plan", "interview_guide"],
        "constraints": {
            "external_write": False,
            "project_scope": "current",
            "time_budget_seconds": None,
        },
        "explicit_skill_names": [],
        "complexity": "assisted",
    }

    planned_skill_ids: dict[str, str] = {}

    def planner_responder(call):  # noqa: ANN001, ANN202
        payload = _last_user_payload(call)
        candidates = payload["candidates"]
        assert isinstance(candidates, list)
        by_name = {
            item["skill_name"]: item
            for item in candidates
            if isinstance(item, dict) and isinstance(item.get("skill_name"), str)
        }
        research = by_name["generate-research-plan"]
        interview = by_name["generate-interview-guide"]
        planned_skill_ids.update(
            research=str(research["skill_id"]),
            interview=str(interview["skill_id"]),
        )
        return [
            assistant_message(
                json.dumps(
                    {
                        "output_contract": ["research_plan", "interview_guide"],
                        "nodes": [
                            {
                                "id": "node_research_plan",
                                "skill_id": research["skill_id"],
                                "skill_version": research["skill_version"],
                                "skill_content_hash": research["skill_content_hash"],
                                "reason": "先明确研究目标、方法和样本",
                                "required": True,
                                "depends_on": [],
                                "input_bindings": ["user.design_requirement"],
                                "output_contract": ["research_plan"],
                                "side_effect": research["side_effect"],
                            },
                            {
                                "id": "node_interview_guide",
                                "skill_id": interview["skill_id"],
                                "skill_version": interview["skill_version"],
                                "skill_content_hash": interview["skill_content_hash"],
                                "reason": "基于研究计划形成可执行访谈提纲",
                                "required": True,
                                "depends_on": ["node_research_plan"],
                                "input_bindings": ["node_research_plan.research_plan"],
                                "output_contract": ["interview_guide"],
                                "side_effect": interview["side_effect"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        ]

    def node_responder(call):  # noqa: ANN001, ANN202
        payload = _last_user_payload(call)
        is_research = payload["skill_id"] == planned_skill_ids["research"]
        deliverable_markdown = (
            "### 研究目标\n验证 AI 助手是否能降低设计任务启动成本。\n\n"
            "### 研究安排\n招募 8 名企业设计师，完成探索访谈与任务测试。"
            if is_research
            else "### 访谈问题\n1. 请回忆最近一次接收设计需求的过程。\n"
            "2. 哪些信息缺失会导致你无法开始工作？\n\n"
            "### 追问\n请展示当时使用的 Brief，并说明判断依据。"
        )
        return [
            assistant_message(
                json.dumps(
                    {
                        "node_id": payload["node_id"],
                        "skill_id": payload["skill_id"],
                        "summary": "研究计划已形成" if is_research else "访谈提纲已形成",
                        "deliverable_markdown": deliverable_markdown,
                        "findings": ["研究目标和样本已明确"] if is_research else ["问题顺序可直接执行"],
                        "recommendations": ["按计划招募用户"] if is_research else ["先试访一名用户"],
                        "sources": [],
                        "confidence": 0.9,
                        "limitations": [],
                        "artifact_ids": [],
                    },
                    ensure_ascii=False,
                )
            )
        ]

    def synthesis_responder(call):  # noqa: ANN001, ANN202
        payload = _last_user_payload(call)
        results = payload["node_results"]
        assert isinstance(results, list) and len(results) == 2
        assert all("deliverable_markdown" not in result for result in results)
        return [
            assistant_message(
                json.dumps(
                    {
                        "summary": f"研究计划与访谈提纲已完成 [{results[0]['id']}]",
                        "sections": [],
                        "claims": [
                            {
                                "text": "建议按研究计划试访一名用户",
                                "node_result_ids": [result["id"] for result in results],
                                "source_ids": [],
                                "recommendation": True,
                            }
                        ],
                        "limitations": [],
                        "next_actions": ["招募并试访一名用户"],
                        "artifact_ids": [],
                    },
                    ensure_ascii=False,
                )
            )
        ]

    model = ScriptedModel(
        [
            [assistant_message(json.dumps(intent, ensure_ascii=False))],
            ModelStep.respond(planner_responder),
            ModelStep.respond(node_responder),
            ModelStep.respond(node_responder),
            ModelStep.respond(synthesis_responder),
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "catalog_service", lambda: catalog)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    previous_override = app.dependency_overrides.get(current_user)
    had_override = current_user in app.dependency_overrides
    app.dependency_overrides[current_user] = lambda: USER

    async def scenario() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start_response = await client.post(
                "/api/agent/runs",
                json={
                    "content": "先制定用户研究计划，再生成访谈提纲",
                    "client_turn_id": "turn_orchestration_mainline",
                    "orchestration_mode": "auto",
                },
            )
            assert start_response.status_code == 202
            started_run = start_response.json()["item"]
            assert started_run["status"] == "planning"
            assert (
                datetime.fromisoformat(started_run["deadline_at"])
                - datetime.fromisoformat(started_run["created_at"])
            ).total_seconds() == 900
            run_id = started_run["id"]

            for _ in range(100):
                waiting_response = await client.get(f"/api/agent/runs/{run_id}")
                assert waiting_response.status_code == 200
                if waiting_response.json()["item"]["status"] == "waiting_plan_approval":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("run did not reach waiting_plan_approval")

            waiting_plan_response = await client.get(f"/api/agent/runs/{run_id}/plan")
            assert waiting_plan_response.status_code == 200
            waiting_plan = waiting_plan_response.json()["plan"]
            assert waiting_plan["status"] == "waiting_approval"
            assert [node["id"] for node in waiting_plan["nodes"]] == [
                "node_research_plan",
                "node_interview_guide",
            ]

            approval_response = await client.post(
                f"/api/agent/runs/{run_id}/plan/approve",
                json={"expected_version": waiting_plan["version"]},
            )
            assert approval_response.status_code == 200
            assert approval_response.json()["run"]["status"] == "running"

            stream_response = await client.get(f"/api/agent/runs/{run_id}/events/stream")
            assert stream_response.status_code == 200
            streamed_events = [
                line.removeprefix("event: ")
                for line in stream_response.text.splitlines()
                if line.startswith("event: ")
            ]
            core_events = [
                "run_started",
                "intent_normalized",
                "skill_candidates_ranked",
                "plan_created",
                "plan_waiting_approval",
                "plan_approved",
                "plan_execution_started",
                "node_ready",
                "node_started",
                "node_completed",
                "synthesis_started",
                "synthesis_completed",
                "run_completed",
            ]
            _assert_ordered_subsequence(streamed_events, core_events)

            run_response = await client.get(f"/api/agent/runs/{run_id}")
            assert run_response.status_code == 200
            completed_run = run_response.json()["item"]
            assert completed_run["status"] == "completed"
            assert completed_run["orchestration_mode"] == "execute"
            assert completed_run["plan_id"]
            assert completed_run["output_text"]
            assert "## 研究计划" in completed_run["output_text"]
            assert "招募 8 名企业设计师" in completed_run["output_text"]
            assert "## 访谈提纲" in completed_run["output_text"]
            assert "请回忆最近一次接收设计需求的过程" in completed_run["output_text"]
            assert "node_result_" not in completed_run["output_text"]

            plan_response = await client.get(f"/api/agent/runs/{run_id}/plan")
            assert plan_response.status_code == 200
            plan_detail = plan_response.json()
            plan = plan_detail["plan"]
            assert plan["status"] == "completed"
            assert len(plan["nodes"]) == 2
            assert all(node["status"] == "completed" for node in plan["nodes"])
            assert len(plan_detail["results"]) == 2
            assert {result["node_id"] for result in plan_detail["results"]} == {
                "node_research_plan",
                "node_interview_guide",
            }
            assert all(result["deliverable_markdown"] for result in plan_detail["results"])
            assert plan_detail["synthesis"]["summary"] == "研究计划与访谈提纲已完成"
            assert plan_detail["synthesis"]["sections"] == [
                "## 研究计划\n\n### 研究目标\n验证 AI 助手是否能降低设计任务启动成本。\n\n"
                "### 研究安排\n招募 8 名企业设计师，完成探索访谈与任务测试。",
                "## 访谈提纲\n\n### 访谈问题\n1. 请回忆最近一次接收设计需求的过程。\n"
                "2. 哪些信息缺失会导致你无法开始工作？\n\n"
                "### 追问\n请展示当时使用的 Brief，并说明判断依据。",
            ]

            events_response = await client.get(f"/api/agent/runs/{run_id}/events")
            assert events_response.status_code == 200
            events = events_response.json()["items"]
            sequences = [event["sequence"] for event in events]
            assert sequences == sorted(set(sequences))
            assert [event["event_type"] for event in events] == streamed_events

        durable_repository = SQLiteStore(repository.db_path)
        durable_run = durable_repository.get_agent_run(run_id)
        durable_plan = durable_repository.get_skill_plan(plan["id"])
        assert durable_run is not None and durable_run.status.value == "completed"
        assert durable_run.plan_id == plan["id"]
        assert durable_plan is not None and durable_plan.status.value == "completed"
        assert len(durable_repository.list_skill_node_results(plan["id"])) == 2
        assert [event.sequence for event in durable_repository.list_agent_run_events(run_id)] == sequences

    try:
        asyncio.run(scenario())
    finally:
        if had_override:
            app.dependency_overrides[current_user] = previous_override
        else:
            app.dependency_overrides.pop(current_user, None)

    model.assert_complete()
    assert len(model.calls) == 5
    assert [call.streamed for call in model.calls] == [False, False, True, True, False]
    node_calls = [call for call in model.calls if call.streamed]
    assert all(call.model_settings.max_tokens == 8_192 for call in node_calls)
    assert all(
        "never exceed 3,000 Chinese characters" in (call.system_instructions or "")
        for call in node_calls
    )
    assert all(
        "read no more than 12 resource paths in total" in (call.system_instructions or "")
        for call in node_calls
    )
    assert model.calls[-1].model_settings.max_tokens == 4_096
