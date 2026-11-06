from __future__ import annotations

import asyncio
import json

import pytest
from agents import Agent, RunConfig, Runner
from agents.testing import ModelStep, ScriptedModel, assistant_message
from httpx import ASGITransport, AsyncClient

import agentmesh.routes.agent_runs as agent_run_routes
import agentmesh.routes.chat as chat_routes
import agentmesh.routes.runners as runner_routes
import agentmesh.runner_auth as runner_auth
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.routes.deps import current_user
from agentmesh.runner_auth import AuthenticatedRunner, hash_runner_token, require_current_runner
from agentmesh.runner_contracts import RunnerCredentialV1, RunnerDeviceV1
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


def _last_user_payload(call) -> dict[str, object]:  # noqa: ANN001
    value = call.input
    if isinstance(value, str):
        return json.loads(value)
    item = next(entry for entry in reversed(value) if entry.get("role") == "user")
    content = item["content"]
    if isinstance(content, str):
        return json.loads(content)
    text = "".join(part["text"] for part in content if part.get("type") == "input_text")
    return json.loads(text)


@pytest.mark.parametrize("separate_devices", [False, True])
def test_standard_plan_nodes_execute_through_local_runner(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
    separate_devices,
) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    monkeypatch.setenv("AGENTMESH_AGENT_RUNTIME", "v2")
    monkeypatch.setenv("AGENTMESH_EXECUTION_LOCATION", "runner")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setenv('AGENTMESH_MEMORY_CONTEXT', 'inject')
    repository = SQLiteStore(tmp_path / "runner-plan.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="test")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    selected_ids: dict[str, str] = {}

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

    def planner(call):  # noqa: ANN001, ANN202
        candidates = _last_user_payload(call)["candidates"]
        by_name = {item["skill_name"]: item for item in candidates}
        research = by_name["generate-research-plan"]
        interview = by_name["generate-interview-guide"]
        selected_ids.update(research=research["skill_id"], interview=interview["skill_id"])
        return [
            assistant_message(
                json.dumps(
                    {
                        "output_contract": ["research_plan", "interview_guide"],
                        "nodes": [
                            {
                                "id": "node_research",
                                "skill_id": research["skill_id"],
                                "skill_version": research["skill_version"],
                                "skill_content_hash": research["skill_content_hash"],
                                "reason": "research first",
                                "required": True,
                                "depends_on": [],
                                "input_bindings": ["user.design_requirement"],
                                "output_contract": ["research_plan"],
                                "side_effect": research["side_effect"],
                            },
                            {
                                "id": "node_interview",
                                "skill_id": interview["skill_id"],
                                "skill_version": interview["skill_version"],
                                "skill_content_hash": interview["skill_content_hash"],
                                "reason": "interview second",
                                "required": True,
                                "depends_on": ["node_research"],
                                "input_bindings": ["node_research.research_plan"],
                                "output_contract": ["interview_guide"],
                                "side_effect": interview["side_effect"],
                            },
                        ],
                    }
                )
            )
        ]

    def synthesis(call):  # noqa: ANN001, ANN202
        results = _last_user_payload(call)["node_results"]
        return [
            assistant_message(
                json.dumps(
                    {
                        "summary": "Local Runner completed the plan",
                        "sections": [],
                        "claims": [
                            {
                                "text": "Both deliverables completed",
                                "node_result_ids": [item["id"] for item in results],
                                "source_ids": [],
                                "recommendation": False,
                            }
                        ],
                        "limitations": [],
                        "next_actions": [],
                        "artifact_ids": [],
                    }
                )
            )
        ]

    model = ScriptedModel(
        [
            [assistant_message(json.dumps(intent))],
            ModelStep.respond(planner),
            ModelStep.respond(synthesis),
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)
    monkeypatch.setattr(runtime, "_select_model", lambda _user: None)
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "catalog_service", lambda: catalog)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)
    monkeypatch.setattr(runner_routes, "store", repository)
    monkeypatch.setattr(runner_auth, "store", repository)

    token = "runner-plan-token"
    device = repository.save_runner_device(
        RunnerDeviceV1(
            id="runner_plan_test",
            owner_user_id=USER.id,
            workspace_id=USER.workspace_id,
            name="Plan Runner",
            capabilities={
                "platform": "darwin",
                "architecture": "arm64",
                "runner_version": "0.1.0",
                'model_capabilities': ['context-handoff-v1'],
            },
        )
    )
    credential = repository.save_runner_credential(
        RunnerCredentialV1(
            id="runner_plan_credential",
            runner_id=device.id,
            token_hash=hash_runner_token(token),
        )
    )
    authenticated = AuthenticatedRunner(device=device, credential=credential, user=USER)
    second_token = "runner-second-plan-token"
    second_device = repository.save_runner_device(device.model_copy(update={"id": "runner_plan_second"}))
    second_credential = repository.save_runner_credential(credential.model_copy(update={
        "id": "runner_plan_second_credential", "runner_id": second_device.id,
        "token_hash": hash_runner_token(second_token),
    }))
    second = AuthenticatedRunner(device=second_device, credential=second_credential, user=USER)
    active_runner = [authenticated]
    previous_user = app.dependency_overrides.get(current_user)
    previous_runner = app.dependency_overrides.get(require_current_runner)
    app.dependency_overrides[current_user] = lambda: USER
    app.dependency_overrides[require_current_runner] = lambda: active_runner[0]

    async def scenario() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post(
                "/api/agent/runs",
                json={
                    "content": "先制定用户研究计划，再生成访谈提纲",
                    "client_turn_id": "turn_runner_plan",
                    "orchestration_mode": "auto",
                },
            )
            assert started.status_code == 202
            run_id = started.json()["item"]["id"]
            for _ in range(100):
                detail = await client.get(f"/api/agent/runs/{run_id}")
                if detail.json()["item"]["status"] == "waiting_plan_approval":
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("plan did not reach approval")
            plan = (await client.get(f"/api/agent/runs/{run_id}/plan")).json()["plan"]
            expected_nodes = [node["id"] for node in plan["nodes"]]
            output_by_node = {node["id"]: node["output_contract"] for node in plan["nodes"]}
            approved = await client.post(
                f"/api/agent/runs/{run_id}/plan/approve",
                json={"expected_version": plan["version"]},
            )
            assert approved.status_code == 200
            cloud_step = MemoryContextService(repository).guard_model_request(
                ScriptedModel([[assistant_message('Bounded cloud step')]]),
                run=repository.get_agent_run(run_id), model_id='cloud-test',
            )
            await Runner.run(Agent(name='Cloud budget step', model=cloud_step), 'Prepare local context',
                             run_config=RunConfig(tracing_disabled=True))

            for index, expected_node in enumerate(expected_nodes):
                active_runner[0] = second if separate_devices and index else authenticated
                node_token = second_token if separate_devices and index else token
                for _ in range(100):
                    claimed = await client.post(
                        "/api/runner/dispatches/claim",
                        headers={"Authorization": f"Bearer {node_token}"},
                        json={"capabilities": device.capabilities.model_dump(mode="json")},
                    )
                    if claimed.status_code == 200:
                        break
                    await asyncio.sleep(0.01)
                else:
                    raise AssertionError(f"Runner did not receive {expected_node}")
                envelope = claimed.json()["envelope"]
                assert envelope["operation_kind"] == "standard_skill_node"
                assert envelope["node_id"] == expected_node
                assert envelope['schema_version'] == 'runner-execution-envelope-v3'
                assert envelope['context'] is not None
                skill_id = envelope["skill"]["id"]
                import agentmesh.runner_executor as runner_executor
                from agentmesh.agent_runtime.model_factory import SelectedSDKModel
                from agentmesh.runner_contracts import RunnerDispatchClaimResponse
                from agentmesh.runner_executor import execute_runner_envelope
                from agentmesh.runner_handoff import RunnerModelHandoff
                from agentmesh.runner_spool import RunnerSpool

                result_payload = {'node_id': expected_node, 'skill_id': skill_id,
                    'summary': f'{expected_node} completed', 'deliverable_markdown': f'# {expected_node}',
                    'delivered_output_kinds': output_by_node[expected_node]}
                local_model = ScriptedModel([[assistant_message(json.dumps(result_payload))]])
                monkeypatch.setattr(runner_executor, 'selected_model_from_env', lambda _id, model=local_model:
                    SelectedSDKModel(model=model, requested_model='default', actual_model='scripted-local'))
                loop = asyncio.get_running_loop()

                class ControlPlane:
                    def __init__(self, event_loop):
                        self.loop = event_loop

                    def authorize_model_handoff(self, lease_id, request):
                        response = asyncio.run_coroutine_threadsafe(client.post(
                            f'/api/runner/dispatches/{lease_id}/model-handoffs',
                            json=request.model_dump(mode='json')), self.loop).result(timeout=10)
                        response.raise_for_status()
                        return response.json()['handoff_id']

                    def confirm_model_handoff(self, lease_id, request):
                        response = asyncio.run_coroutine_threadsafe(client.post(
                            f'/api/runner/dispatches/{lease_id}/model-deliveries',
                            json=request.model_dump(mode='json')), self.loop).result(timeout=10)
                        response.raise_for_status()
                        return response.json()

                parsed = RunnerDispatchClaimResponse.model_validate(claimed.json()).envelope
                actual = await execute_runner_envelope(parsed, handoff=RunnerModelHandoff(
                    ControlPlane(loop), RunnerSpool(tmp_path / f'{expected_node}-spool.sqlite3'), parsed))
                assert len(local_model.calls) == 1
                assert repository.list_memory_use_receipts_for_run(run_id) == []
                completed = await client.post(
                    f"/api/runner/dispatches/{envelope['lease_id']}/node-complete",
                    headers={"Authorization": f"Bearer {node_token}"},
                    json={
                        'schema_version': 'runner-node-completion-v2',
                        "command_id": f"complete-{expected_node}",
                        "result_payload": actual.result_payload,
                        "requested_model": "default",
                        "actual_model": "local-model",
                        "total_tokens": 10,
                    },
                )
                assert completed.status_code == 200

            for _ in range(100):
                detail = await client.get(f"/api/agent/runs/{run_id}")
                if detail.json()["item"]["status"] in {"completed", "partial"}:
                    assert all(node_id in detail.json()["item"]["output_text"] for node_id in expected_nodes)
                    budget = repository.get_run_model_budget(run_id)
                    assert sum(reservation.model_id == 'scripted-local' for reservation in budget.reservations) == 2
                    assert sum(reservation.model_id == 'cloud-test' for reservation in budget.reservations) == 1
                    assert len(budget.reservations) == 3
                    return
                await asyncio.sleep(0.01)
            raise AssertionError(
                f"remote node plan did not complete: {detail.json()} "
                f"events={[event.event_type for event in repository.list_agent_run_events(run_id)]}"
            )

    try:
        asyncio.run(scenario())
    finally:
        if previous_user is None:
            app.dependency_overrides.pop(current_user, None)
        else:
            app.dependency_overrides[current_user] = previous_user
        if previous_runner is None:
            app.dependency_overrides.pop(require_current_runner, None)
        else:
            app.dependency_overrides[require_current_runner] = previous_runner
