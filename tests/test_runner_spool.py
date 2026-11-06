from __future__ import annotations

import httpx
import pytest

from agentmesh.models import now_utc
from agentmesh.runner_contracts import RunnerExecutionEventV1
from agentmesh.runner_spool import RunnerSpool


class _Client:
    def __init__(self):
        self.fail = True
        self.events = []

    def append_events(self, _lease_id, events):
        if self.fail:
            raise OSError("offline")
        self.events.extend(events)


def test_runner_spool_keeps_events_until_upload_is_confirmed(tmp_path) -> None:
    spool = RunnerSpool(tmp_path / "runner-spool.sqlite3")
    client = _Client()
    event = RunnerExecutionEventV1(
        client_event_id="event-1",
        event_type="execution_started",
        occurred_at=now_utc(),
    )
    spool.enqueue_events("lease-1", [event])

    with pytest.raises(OSError, match="offline"):
        spool.flush(client)  # type: ignore[arg-type]
    assert spool.pending_count() == 1

    client.fail = False
    assert spool.flush(client) == 1  # type: ignore[arg-type]
    assert spool.pending_count() == 0
    assert [item.client_event_id for item in client.events] == ["event-1"]


def test_runner_spool_discards_items_for_an_expired_lease(tmp_path) -> None:
    spool = RunnerSpool(tmp_path / "runner-spool.sqlite3")
    event = RunnerExecutionEventV1(
        client_event_id="event-stale",
        event_type="execution_started",
        occurred_at=now_utc(),
    )
    spool.enqueue_events("lease-expired", [event])

    class ExpiredClient:
        @staticmethod
        def append_events(_lease_id, _events):
            request = httpx.Request("POST", "https://mesh.example/api/runner/dispatches/lease/events")
            response = httpx.Response(
                409,
                request=request,
                json={"detail": {"code": "runner_lease_expired"}},
            )
            raise httpx.HTTPStatusError("expired", request=request, response=response)

    assert spool.flush(ExpiredClient()) == 1  # type: ignore[arg-type]
    assert spool.pending_count() == 0
