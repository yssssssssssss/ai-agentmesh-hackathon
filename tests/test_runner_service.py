from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx
import pytest

from agentmesh.models import now_utc
from agentmesh.runner_contracts import (
    RunnerCapabilitiesV1,
    RunnerExecutionEnvelopeV1,
    RunnerExecutionEnvelopeV2,
    RunnerLeaseRenewResponse,
    RunnerSessionCommitV1,
    RunnerSessionSnapshotV1,
    runner_envelope_hash,
)
from agentmesh.runner_executor import RunnerExecutionResult
from agentmesh.runner_service import LocalRunnerService
from agentmesh.runner_spool import RunnerSpool


def _capabilities() -> RunnerCapabilitiesV1:
    return RunnerCapabilitiesV1(
        platform="darwin",
        architecture="arm64",
        runner_version="0.1.0",
    )


def _envelope() -> RunnerExecutionEnvelopeV1:
    now = now_utc()
    return RunnerExecutionEnvelopeV1(
        envelope_hash="a" * 64,
        lease_id="runner_lease_1",
        lease_expires_at=now + timedelta(minutes=5),
        run_id="run_1",
        operation_key="dispatch_1",
        dispatch_generation=1,
        owner_user_id="usr_1",
        workspace_id="ws_1",
        project_id="prj_1",
        thread_id="thread_1",
        input_text="hello",
        instructions="answer directly",
        model_id="default",
        deadline_at=now + timedelta(minutes=5),
    )


class _Client:
    def __init__(self, envelope: RunnerExecutionEnvelopeV1, *, cancel_on_renew: bool = False):
        self.envelope = envelope
        self.cancel_on_renew = cancel_on_renew
        self.events = []
        self.completed = None
        self.failed = None
        self.cancelled = None
        self.heartbeats = 0

    def heartbeat(self, _capabilities):
        self.heartbeats += 1

    def claim(self, _capabilities):
        envelope, self.envelope = self.envelope, None
        return envelope

    def append_events(self, _lease_id, events):
        self.events.extend(events)

    def renew(self, lease_id):
        return RunnerLeaseRenewResponse(
            lease_id=lease_id,
            lease_expires_at=now_utc() + timedelta(minutes=5),
            cancel_requested=self.cancel_on_renew,
        )

    def acknowledge_cancelled(self, _lease_id, request):
        self.cancelled = request

    def complete(self, _lease_id, request):
        self.completed = request

    def fail(self, _lease_id, request):
        self.failed = request


def test_local_runner_service_executes_and_completes_claimed_dispatch(tmp_path) -> None:
    client = _Client(_envelope())

    async def executor(_envelope):
        return RunnerExecutionResult(
            output_text="done",
            requested_model="default",
            actual_model="test-model",
            total_tokens=12,
        )

    service = LocalRunnerService(
        client,
        capabilities=_capabilities(),
        executor=executor,  # type: ignore[arg-type]
        spool=RunnerSpool(tmp_path / "success.sqlite3"),
    )

    assert service.run_once() is True
    assert client.heartbeats == 1
    assert [event.event_type for event in client.events] == [
        "execution_started",
        "model_started",
        "model_completed",
    ]
    assert client.completed.output_text == "done"
    assert client.failed is None


def test_structured_runner_completion_survives_a_spool_restart_without_reexecution(tmp_path):
    payload = _envelope().model_dump(exclude={'schema_version', 'envelope_hash'})
    snapshot = RunnerSessionSnapshotV1(thread_id='thread_1', version=2,
                                       items=[{'role': 'user', 'content': 'Earlier goal'}])
    payload['session'] = snapshot
    envelope = RunnerExecutionEnvelopeV2(envelope_hash=runner_envelope_hash(payload), **payload)

    class OfflineOnce(_Client):
        attempts = 0

        def complete(self, lease_id, request):
            self.attempts += 1
            if self.attempts == 1:
                raise httpx.ConnectError('Temporary offline connection')
            super().complete(lease_id, request)

    client = OfflineOnce(envelope)
    executions = []
    commit = RunnerSessionCommitV1(thread_id='thread_1', version=2, snapshot_hash=snapshot.content_hash,
                                  items=[*snapshot.items, {'role': 'assistant', 'content': 'done'}])

    async def executor(received):
        executions.append(received.envelope_hash)
        return RunnerExecutionResult(output_text='done', requested_model='default', actual_model='scripted',
                                     total_tokens=12, session_commit=commit)

    path = tmp_path / 'structured-spool.sqlite3'
    service = LocalRunnerService(client, capabilities=_capabilities(), executor=executor, spool=RunnerSpool(path))
    with pytest.raises(httpx.ConnectError):
        service.run_once()
    assert client.completed is None
    assert len(executions) == 1
    restored = RunnerSpool(path)
    assert restored.flush(client) == 1
    assert client.completed.schema_version == 'runner-completion-v2'
    assert client.completed.session_commit == commit
    assert len(executions) == 1


def test_local_runner_service_reports_execution_failure(tmp_path) -> None:
    client = _Client(_envelope())

    async def executor(_envelope):
        raise RuntimeError("local secret must not be uploaded")

    service = LocalRunnerService(
        client,
        capabilities=_capabilities(),
        executor=executor,  # type: ignore[arg-type]
        spool=RunnerSpool(tmp_path / "failure.sqlite3"),
    )

    assert service.run_once() is True
    assert client.completed is None
    assert client.failed.error_code == "RuntimeError"
    assert [event.event_type for event in client.events][-1] == "execution_failed"


def test_local_runner_service_acknowledges_control_plane_cancellation(tmp_path) -> None:
    client = _Client(_envelope(), cancel_on_renew=True)

    async def executor(_envelope):
        await asyncio.sleep(60)
        raise AssertionError("cancelled executor should not finish")

    service = LocalRunnerService(
        client,
        capabilities=_capabilities(),
        executor=executor,  # type: ignore[arg-type]
        renew_interval_seconds=0.001,
        spool=RunnerSpool(tmp_path / "cancel.sqlite3"),
    )

    assert service.run_once() is True
    assert client.cancelled is not None
    assert client.completed is None
    assert client.failed is None
