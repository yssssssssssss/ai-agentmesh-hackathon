from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from agents.models.interface import ModelResponse
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.usage import Usage
from fastapi.testclient import TestClient
from test_memory_context import _accepted_memory
from test_runner_dispatch import _capabilities, _enroll_runner

import agentmesh.runner_executor as runner_executor
from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.app import app
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.model_registry import set_agent_model
from agentmesh.models import AgentToolGrant, ModelDefinition
from agentmesh.runner_contracts import (
    RunnerCompletionRequestV2,
    RunnerDispatchClaimResponse,
    RunnerModelDeliveryRequestV1,
    RunnerSessionCommitV1,
)
from agentmesh.runner_handoff import RunnerModelHandoff
from agentmesh.runner_spool import RunnerSpool
from agentmesh.seed import USER
from agentmesh.store import SQLiteStore, store
from agentmesh.task_management.contracts import TaskCreateRequest, TaskTransitionRequest
from agentmesh.task_management.service import TaskManagementService


def setup_function():
    store.reset()


@pytest.fixture
def remote_execution(monkeypatch, tmp_path, request):
    monkeypatch.setenv("AGENTMESH_AGENT_RUNTIME", "v2")
    monkeypatch.setenv("AGENTMESH_EXECUTION_LOCATION", "runner")
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "off")
    monkeypatch.setenv("AGENTMESH_MEMORY_CONTEXT", "inject")
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = TestClient(app)
    token = _enroll_runner(client)
    headers = {"Authorization": f"Bearer {token}"}
    options = getattr(request, 'param', {})
    options = {'tools': True} if options is True else options
    tool_names = ['local_file_read'] if options.get('tools') else []
    if tool_names:
        store.save_agent_tool_grant(AgentToolGrant(agent_id=USER.personal_agent_id,
            tool_id='tool_local_file_read', granted_by=USER.id))
        root = tmp_path / 'tool-root'
        root.mkdir()
        (root / 'notes.md').write_text('allowed runner evidence', encoding='utf-8')
        (root / 'other.md').write_text('must be refused by the quota', encoding='utf-8')
        monkeypatch.setenv('AGENTMESH_RUNNER_ALLOWED_ROOTS', str(root))
    capabilities = ['structured-session-v1', 'context-handoff-v1']
    if options.get('tool_handoff', True):
        capabilities.append('tool-handoff-v1')
    task = (
        TaskManagementService(store)
        .create_task(TaskCreateRequest(command_id="remote-context-task", title="Checkout context"), USER)
        .task
    )
    for action in ("plan", "start"):
        task = (
            TaskManagementService(store)
            .transition_task(
                task.id,
                TaskTransitionRequest(
                    command_id="remote-context-" + action, expected_version=task.management.version, action=action
                ),
                USER,
            )
            .task
        )
    memory = _accepted_memory(store, "memory_remote_delivery")
    created = client.post(
        "/api/agent/runs",
        json={
            "content": "checkout evidence reusable guidance",
            "task_id": task.id,
            "client_turn_id": "remote-context",
            "orchestration_mode": "single",
            "planning_mode": "standard",
        },
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["item"]["id"]
    claim = client.post(
        "/api/runner/dispatches/claim",
        headers=headers,
        json={
            "capabilities": {
                **_capabilities(tools=tool_names),
                "model_capabilities": capabilities,
            }
        },
    )
    assert claim.status_code == 200
    assert claim.json()["envelope"]["schema_version"] == "runner-execution-envelope-v3"
    assert store.list_memory_use_receipts_for_run(run_id) == []
    envelope = RunnerDispatchClaimResponse.model_validate(claim.json()).envelope
    return client, headers, envelope, memory


@pytest.mark.parametrize("offline_confirmation", [False, True])
def test_remote_memory_is_prepared_until_actual_model_response_then_delivered_once(
    tmp_path,
    monkeypatch,
    remote_execution,
    offline_confirmation,
):
    client, headers, envelope, memory = remote_execution
    run_id = envelope.run_id
    early = RunnerCompletionRequestV2(
        command_id="remote-complete",
        output_text="Pending result",
        session_commit=RunnerSessionCommitV1(
            **envelope.session.model_dump(exclude={"schema_version"}), snapshot_hash=envelope.session.content_hash
        ),
    )
    denied = client.post(
        f"/api/runner/dispatches/{envelope.lease_id}/complete", headers=headers, json=early.model_dump(mode="json")
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "runner_model_delivery_required"

    class ControlPlane:
        def __init__(self):
            self.deliveries = []
            self.offline = offline_confirmation

        def authorize_model_handoff(self, lease_id, request):
            response = client.post(
                f"/api/runner/dispatches/{lease_id}/model-handoffs",
                headers=headers,
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            assert store.list_memory_use_receipts_for_run(run_id) == []
            return response.json()["handoff_id"]

        def confirm_model_handoff(self, lease_id, request):
            self.deliveries.append(request)
            if self.offline:
                raise httpx.ConnectError("isolated control-plane outage")
            response = client.post(
                f"/api/runner/dispatches/{lease_id}/model-deliveries",
                headers=headers,
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            return response.json()

        def complete(self, lease_id, request):
            response = client.post(
                f"/api/runner/dispatches/{lease_id}/complete", headers=headers, json=request.model_dump(mode="json")
            )
            response.raise_for_status()
            return response.json()

    def answer(call):
        assert memory.summary in call.system_instructions
        assert store.list_memory_use_receipts_for_run(run_id) == []
        return ModelResponse(
            output=[assistant_message("The confirmed guidance preserves address edits.")],
            usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12),
            response_id="remote-response",
        )

    model = ScriptedModel([ModelStep.respond(answer)])
    monkeypatch.setattr(
        runner_executor,
        "selected_model_from_env",
        lambda _id: SelectedSDKModel(model=model, requested_model="default", actual_model="scripted-local"),
    )
    control = ControlPlane()
    spool_path = tmp_path / "handoff-spool.sqlite3"
    spool = RunnerSpool(spool_path)
    handoff = RunnerModelHandoff(control, spool, envelope)
    result = asyncio.run(runner_executor.execute_runner_envelope(envelope, handoff=handoff))
    assert result.output_text == "The confirmed guidance preserves address edits."
    if offline_confirmation:
        assert store.list_memory_use_receipts_for_run(run_id) == []
        assert spool.pending_count() == 1
    completion = RunnerCompletionRequestV2(
        command_id="remote-complete",
        output_text=result.output_text,
        session_commit=result.session_commit,
        total_tokens=result.total_tokens,
    )
    spool.enqueue_completion(envelope.lease_id, completion)
    control.offline = False
    reopened = RunnerSpool(spool_path)
    assert reopened.flush(control) == (2 if offline_confirmation else 1)
    assert reopened.pending_count() == 0
    assert len(model.calls) == 1
    budget = store.get_run_model_budget(run_id)
    assert len(budget.reservations) == 1 and budget.total_tokens == 12 and budget.output_tokens == 2
    receipts = store.list_memory_use_receipts_for_run(run_id)
    assert len(receipts) == 1 and receipts[0].memory_id == memory.id and receipts[0].memory_version == memory.version
    session = store.get_sdk_session(envelope.thread_id)
    assert {reference.memory_id for reference in session.memory_dependencies} == {memory.id}
    control.confirm_model_handoff(envelope.lease_id, control.deliveries[0])
    control.complete(envelope.lease_id, completion)
    assert len(store.list_memory_use_receipts_for_run(run_id)) == 1


def _authorize_remote(client, headers, envelope, identity, *, stage="execution"):
    return client.post(
        f"/api/runner/dispatches/{envelope.lease_id}/model-handoffs",
        headers=headers,
        json={
            "client_request_id": identity,
            "envelope_hash": envelope.envelope_hash,
            "request_hash": canonical_json_sha256({"request": identity}),
            "stage": stage,
            "input_hashes": [canonical_json_sha256({"input": envelope.input_text})],
            "instructions_hash": canonical_json_sha256({"instructions": envelope.instructions}),
            "model_id": "scripted-local",
            "total_chars": 1000,
            "estimated_input_tokens": 3000,
            "output_token_cap": 100,
        },
    )


def test_remote_compaction_execution_and_retries_share_frozen_budget(remote_execution, monkeypatch):
    client, headers, envelope, _memory = remote_execution
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_MAX_CALLS", "2")
    first = _authorize_remote(client, headers, envelope, "compaction", stage="compaction")
    assert first.status_code == 200, first.text
    replay = _authorize_remote(client, headers, envelope, "compaction", stage="compaction")
    assert replay.json() == first.json()
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_MAX_CALLS", "100")
    second = _authorize_remote(client, headers, envelope, "execution")
    assert second.status_code == 200, second.text
    refused = _authorize_remote(client, headers, envelope, "retry")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "run_model_budget_exhausted"
    reopened = SQLiteStore(store.db_path)
    try:
        budget = reopened.get_run_model_budget(envelope.run_id)
        assert budget.limits.max_calls == 2
        assert len(budget.reservations) == 2 and budget.total_tokens == 6200
    finally:
        reopened.close()
    assert store.list_memory_use_receipts_for_run(envelope.run_id) == []


def test_remote_late_usage_settles_cost_without_restoring_cancelled_context(remote_execution):
    client, headers, envelope, _memory = remote_execution
    permit = _authorize_remote(client, headers, envelope, "late-usage")
    assert permit.status_code == 200
    cancelled = client.post(f"/api/agent/runs/{envelope.run_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    payload = {
        "handoff_id": permit.json()["handoff_id"],
        "request_hash": canonical_json_sha256({"request": "late-usage"}),
        "total_tokens": 12,
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    for _ in range(2):
        refused = client.post(
            f"/api/runner/dispatches/{envelope.lease_id}/model-deliveries", headers=headers, json=payload
        )
        assert refused.status_code == 409, refused.text
    budget = store.get_run_model_budget(envelope.run_id)
    assert len(budget.reservations) == 1 and budget.total_tokens == 12
    assert budget.reservations[0].status == "settled"
    assert store.list_memory_use_receipts_for_run(envelope.run_id) == []


def test_remote_price_limit_uses_frozen_cloud_rates(remote_execution, monkeypatch):
    client, headers, envelope, _memory = remote_execution
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_MAX_COST_MICROS", "5000")
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_COST_CURRENCY", "CNY")
    price = {
        "currency": "CNY",
        "version": "test-v1",
        "input_micros_per_million_tokens": 1000000,
        "output_micros_per_million_tokens": 1000000,
    }
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_PRICES_JSON", json.dumps({"scripted-local": price}))
    first = _authorize_remote(client, headers, envelope, "priced-request")
    assert first.status_code == 200, first.text
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_MAX_COST_MICROS", "999999")
    monkeypatch.setenv("AGENTMESH_RUN_MODEL_PRICES_JSON", "{}")
    refused = _authorize_remote(client, headers, envelope, "expensive-retry")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "run_model_budget_exhausted"
    budget = store.get_run_model_budget(envelope.run_id)
    assert budget.estimated_cost_micros == 3100 and budget.cost_currency == "CNY"
    assert budget.reported_estimated_cost_micros is None


def test_offline_over_cap_delivery_fails_run_and_withholds_queued_completion(remote_execution, tmp_path):
    client, headers, envelope, _memory = remote_execution
    permit = _authorize_remote(client, headers, envelope, "over-output-cap")
    assert permit.status_code == 200
    from agentmesh.agent_runtime.budget import RunModelUsageV1

    delivery = RunnerModelDeliveryRequestV1(
        handoff_id=permit.json()["handoff_id"],
        request_hash=canonical_json_sha256({"request": "over-output-cap"}),
        total_tokens=111,
        usage=RunModelUsageV1(input_tokens=10, output_tokens=101),
    )
    spool = RunnerSpool(tmp_path / "over-cap-spool.sqlite3")
    spool.enqueue_model_delivery(envelope.lease_id, delivery)
    spool.enqueue_completion(
        envelope.lease_id,
        RunnerCompletionRequestV2(
            command_id="must-not-complete",
            output_text="Over-cap result",
            session_commit=RunnerSessionCommitV1(
                **envelope.session.model_dump(exclude={"schema_version"}), snapshot_hash=envelope.session.content_hash
            ),
        ),
    )

    class ControlPlane:
        def confirm_model_handoff(self, lease_id, request):
            response = client.post(
                f"/api/runner/dispatches/{lease_id}/model-deliveries",
                headers=headers,
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            return response.json()

        def fail(self, lease_id, request):
            response = client.post(
                f"/api/runner/dispatches/{lease_id}/fail", headers=headers, json=request.model_dump(mode="json")
            )
            response.raise_for_status()

        def complete(self, *_args):
            pytest.fail("over-cap result must not complete")

    assert spool.flush(ControlPlane()) == 1
    assert spool.pending_count() == 0
    run = store.get_agent_run(envelope.run_id)
    assert run.status.value == "failed" and run.error_code == "run_model_request_usage_exceeded"
    budget = store.get_run_model_budget(run.id)
    assert budget.total_tokens == 111 and budget.output_tokens == 101


class RemoteControlPlane:
    def __init__(self, client, headers, *, after_response=None):
        self.client = client
        self.headers = headers
        self.after_response = after_response
        self.tool_requests = []

    def _post(self, lease_id, action, request):
        response = self.client.post(f'/api/runner/dispatches/{lease_id}/{action}', headers=self.headers,
                                    json=request.model_dump(mode='json'))
        # Starlette's test transport uses httpx2; the real Runner client uses httpx.
        httpx.Response(response.status_code, content=response.content,
                       request=httpx.Request('POST', str(response.request.url))).raise_for_status()
        return response.json()

    def authorize_model_handoff(self, lease_id, request):
        return self._post(lease_id, 'model-handoffs', request)['handoff_id']

    def confirm_model_handoff(self, lease_id, request):
        result = self._post(lease_id, 'model-deliveries', request)
        if self.after_response is not None:
            self.after_response()
        return result

    def authorize_tool_handoff(self, lease_id, request):
        self.tool_requests.append(request)
        result = self._post(lease_id, 'tool-handoffs', request)
        assert self._post(lease_id, 'tool-handoffs', request) == result
        return result['handoff_id']


@pytest.mark.parametrize('remote_execution', [True], indirect=True)
def test_remote_file_reads_share_local_tool_quota_before_actual_io(remote_execution, tmp_path, monkeypatch):
    client, headers, envelope, _memory = remote_execution
    monkeypatch.setenv('AGENTMESH_RUN_MAX_TOOL_CALLS', '2')
    assert store.consume_agent_run_tool_call(envelope.run_id) == 1
    model = ScriptedModel([
        [function_call('local_file_read', {'path': 'notes.md'}, call_id='remote-read-1')],
        [function_call('local_file_read', {'path': 'other.md'}, call_id='remote-read-2')],
        [assistant_message('unreachable')],
    ])
    monkeypatch.setattr(runner_executor, 'selected_model_from_env', lambda _id:
        SelectedSDKModel(model=model, requested_model=envelope.model_id, actual_model='scripted-local'))
    control = RemoteControlPlane(client, headers)
    handoff = RunnerModelHandoff(control, RunnerSpool(tmp_path / 'tool-quota.sqlite3'), envelope)
    with pytest.raises(RuntimeError, match='run_tool_budget_exhausted'):
        asyncio.run(runner_executor.execute_runner_envelope(envelope, handoff=handoff))
    assert len(model.calls) == 2
    assert 'allowed runner evidence' in str(model.calls[1].input)
    assert len(control.tool_requests) == 2
    assert store.get_agent_run(envelope.run_id).tool_call_count == 2
    assert store.get_run_model_budget(envelope.run_id).limits.max_tool_calls == 2


@pytest.mark.parametrize('remote_execution', [True], indirect=True)
@pytest.mark.parametrize('change', ['tool', 'model'])
def test_remote_tool_rechecks_grant_and_model_policy_after_model_response(
    remote_execution, tmp_path, monkeypatch, change,
):
    client, headers, envelope, _memory = remote_execution

    def revoke():
        if change == 'tool':
            grant = next(grant for grant in store.list_agent_tool_grants(USER.personal_agent_id)
                         if grant.tool_id == 'tool_local_file_read')
            store.save_agent_tool_grant(grant.model_copy(update={'enabled': False}))
        else:
            store.save_model_definition(ModelDefinition(id='replacement-model', label='Replacement',
                provider='test', model_name='replacement'))
            set_agent_model(store, store.get_agent(USER.personal_agent_id), 'replacement-model')

    model = ScriptedModel([[function_call('local_file_read', {'path': 'notes.md'}, call_id='revoked-read')],
                           [assistant_message('unreachable')]])
    monkeypatch.setattr(runner_executor, 'selected_model_from_env', lambda _id:
        SelectedSDKModel(model=model, requested_model=envelope.model_id, actual_model='scripted-local'))
    handoff = RunnerModelHandoff(RemoteControlPlane(client, headers, after_response=revoke),
                                RunnerSpool(tmp_path / 'revoked-tool.sqlite3'), envelope)
    expected = 'runner_tool_grant_changed' if change == 'tool' else 'runner_model_policy_changed'
    with pytest.raises(RuntimeError, match=expected):
        asyncio.run(runner_executor.execute_runner_envelope(envelope, handoff=handoff))
    assert len(model.calls) == 1
    assert store.get_agent_run(envelope.run_id).tool_call_count == 0


@pytest.mark.parametrize('remote_execution', [{'tools': True, 'tool_handoff': False}], indirect=True)
def test_old_context_client_does_not_receive_unmetered_file_tools(remote_execution):
    _client, _headers, envelope, _memory = remote_execution
    assert envelope.tools == []


def test_remote_lease_keeps_first_actual_model_identity(remote_execution):
    client, headers, envelope, _memory = remote_execution
    first = _authorize_remote(client, headers, envelope, 'first-model')
    assert first.status_code == 200, first.text
    changed = json.loads(first.request.content)
    changed.update(client_request_id='replacement', model_id='replacement-model')
    refused = client.post(f'/api/runner/dispatches/{envelope.lease_id}/model-handoffs',
                          headers=headers, json=changed)
    assert refused.status_code == 409
    assert refused.json()['detail']['code'] == 'runner_actual_model_changed'
    assert len(store.get_run_model_budget(envelope.run_id).reservations) == 1
