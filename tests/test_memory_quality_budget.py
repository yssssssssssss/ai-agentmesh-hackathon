from __future__ import annotations

import json

import pytest

from eval.memory_quality import BatchBudget, BatchBudgetExceeded, failure_code, write_checkpoint


def test_unknown_attempt_reservation_survives_checkpoint_and_blocks_another_call(tmp_path):
    budget = BatchBudget(1000)
    budget.reserve(600)
    report = {'status': 'running', 'cases': []}
    path = tmp_path / 'pilot.json'
    write_checkpoint(path, report, budget)
    assert json.loads(path.read_text())['reserved_unknown_or_inflight_tokens'] == 600
    with pytest.raises(BatchBudgetExceeded):
        budget.reserve(401)
    assert budget.reserved == 600 and budget.spent == 0
    budget.settle(reservation=600, measured=250)
    write_checkpoint(path, report, budget)
    saved = json.loads(path.read_text())
    assert saved['model_tokens'] == 250 and saved['reserved_unknown_or_inflight_tokens'] == 0
    budget.reserve(750)
    with pytest.raises(BatchBudgetExceeded):
        budget.reserve(1)


def test_provider_overruns_stop_the_batch_without_discarding_actual_usage():
    budget = BatchBudget(1000)
    budget.reserve(800)
    with pytest.raises(BatchBudgetExceeded):
        budget.settle(reservation=800, measured=1001)
    assert budget.spent == 1001 and budget.reserved == 0


def test_connection_failure_diagnostic_has_no_provider_body_or_credentials():
    import httpx
    from openai import APIConnectionError

    error = APIConnectionError(message='password=never-record-this', request=httpx.Request('POST', 'https://example.invalid'))
    assert failure_code(error) == 'provider_connection_failed'
    assert 'never-record-this' not in failure_code(error)
