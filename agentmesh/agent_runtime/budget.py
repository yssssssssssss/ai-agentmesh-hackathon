"""Durable accounting for ordinary local and remote model requests, shared by the Run."""
from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable
from contextlib import closing
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal

from agents.models.interface import Model
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from agentmesh.agent_runtime.pricing import RunModelPriceBookV1, RunModelPriceV1
from agentmesh.memory_context.request_budget import (
    ContextRequestBudgetV1,
    ModelAdmissionError,
    measure_model_request,
    model_request_payload,
)
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    SkillPlan,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    new_id,
    now_utc,
)

if TYPE_CHECKING:
    from agentmesh.agent_runtime.models import AgentMeshRunContext
    from agentmesh.store import SQLiteStore


class RunModelBudgetError(ModelAdmissionError):
    pass


class RunModelBudgetLimitsV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    max_calls: int = Field(default=32, ge=1, le=128)
    max_tokens: int = Field(default=256000, ge=1, le=2000000)
    max_output_tokens: int = Field(default=65536, ge=1, le=1000000)
    max_request_attempts: int = Field(default=3, ge=1, le=8)
    max_tool_calls: int = Field(default=24, ge=1, le=24)
    cost_currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    max_cost_micros: int | None = Field(default=None, ge=0, le=1000000000000)

    @model_validator(mode='after')
    def cost_limit_has_currency(self) -> RunModelBudgetLimitsV1:
        if (self.cost_currency is None) != (self.max_cost_micros is None):
            raise ValueError('cost limit requires an explicit currency')
        return self

    @classmethod
    def from_env(cls) -> RunModelBudgetLimitsV1:
        try:
            values = {key: int(value) for key in cls.model_fields if key not in {
                'cost_currency', 'max_cost_micros', 'max_tool_calls'}
                      and (value := os.getenv('AGENTMESH_RUN_MODEL_' + key.upper())) is not None}
            if (tool_limit := os.getenv('AGENTMESH_RUN_MAX_TOOL_CALLS')) is not None:
                values['max_tool_calls'] = int(tool_limit)
            if cost := os.getenv('AGENTMESH_RUN_MODEL_MAX_COST_MICROS'):
                values['max_cost_micros'] = int(cost)
            if currency := os.getenv('AGENTMESH_RUN_MODEL_COST_CURRENCY'):
                values['cost_currency'] = currency
            return cls(**values)
        except ValueError as error:
            raise RunModelBudgetError('run_model_budget_configuration_invalid') from error


class RunModelUsageV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_reported(cls, reported: object) -> RunModelUsageV1 | None:
        parts = [getattr(reported, key, None) for key in ('input_tokens', 'output_tokens', 'total_tokens')]
        if all(type(value) is int and value >= 0 for value in parts) and parts[2] > 0 and sum(parts[:2]) == parts[2]:
            return cls(input_tokens=parts[0], output_tokens=parts[1])
        return None


class RunModelReservationV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    invocation_id: str = Field(min_length=1, max_length=128)
    request_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    execution_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    model_id: str = Field(min_length=1, max_length=256)
    input_token_estimate: int = Field(ge=0, le=1000000)
    output_token_cap: int = Field(ge=1, le=32000)
    status: Literal['reserved', 'settled', 'unknown'] = 'reserved'
    usage: RunModelUsageV1 | None = None
    price: RunModelPriceV1 | None = None
    reserved_at: AwareDatetime | None = None

    @property
    def estimated_cost_micros(self) -> int | None:
        if self.price is None:
            return None
        return self.price.estimate_micros(
            self.usage.input_tokens if self.usage is not None else self.input_token_estimate,
            self.usage.output_tokens if self.usage is not None else self.output_token_cap,
        )


class RunModelBudgetV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    run_id: str
    limits: RunModelBudgetLimitsV1
    reservations: list[RunModelReservationV1] = Field(default_factory=list, max_length=128)
    price_book: RunModelPriceBookV1 = Field(default_factory=RunModelPriceBookV1)

    @property
    def cost_currency(self) -> str | None:
        if not self.reservations:
            return self.limits.cost_currency
        if any(r.price is None for r in self.reservations):
            return None
        currencies = {r.price.currency for r in self.reservations}
        return next(iter(currencies)) if len(currencies) == 1 else None

    @property
    def estimated_cost_micros(self) -> int | None:
        if self.cost_currency is None:
            return None
        return sum(r.estimated_cost_micros for r in self.reservations)

    @property
    def reported_estimated_cost_micros(self) -> int | None:
        return self.estimated_cost_micros if all(r.usage is not None for r in self.reservations) else None

    @property
    def total_tokens(self) -> int:
        return sum(r.usage.total_tokens if r.usage is not None else r.input_token_estimate + r.output_token_cap
                   for r in self.reservations)

    @property
    def output_tokens(self) -> int:
        return sum(r.usage.output_tokens if r.usage is not None else r.output_token_cap for r in self.reservations)

    @property
    def exhausted(self) -> bool:
        return (len(self.reservations) > self.limits.max_calls or self.total_tokens > self.limits.max_tokens
                or self.output_tokens > self.limits.max_output_tokens
                or (self.limits.max_cost_micros is not None and (
                    self.estimated_cost_micros is None or self.estimated_cost_micros > self.limits.max_cost_micros)))


def _read_budget(connection, run_id: str) -> RunModelBudgetV1 | None:  # noqa: ANN001
    row = connection.execute('SELECT payload FROM run_model_budgets WHERE run_id = ?', (run_id,)).fetchone()
    if row is None:
        return None
    try:
        if len(row['payload'].encode('utf-8')) > 262144:
            raise ValueError
        budget = RunModelBudgetV1.model_validate_json(row['payload'])
        if (budget.run_id != run_id or len(budget.reservations) > budget.limits.max_calls
            or len({r.invocation_id for r in budget.reservations}) != len(budget.reservations)
            or any((r.status == 'settled') != (r.usage is not None) for r in budget.reservations)
            or any(r.price is not None and (r.price != budget.price_book.prices.get(r.model_id)
                    or r.reserved_at is None or not r.price.active_at(r.reserved_at)) for r in budget.reservations)
            or (budget.limits.max_cost_micros is not None and any(
                r.price is None or r.price.currency != budget.limits.cost_currency for r in budget.reservations))):
            raise ValueError
        return budget
    except (TypeError, ValueError) as error:
        raise RunModelBudgetError('run_model_budget_integrity_failed') from error


def get_budget(repository: SQLiteStore, run_id: str) -> RunModelBudgetV1 | None:
    with closing(repository._read_connect()) as connection:
        return _read_budget(connection, run_id)


def _save_budget(connection, budget: RunModelBudgetV1) -> None:  # noqa: ANN001
    connection.execute('INSERT INTO run_model_budgets(run_id, payload) VALUES (?, ?) '
                       'ON CONFLICT(run_id) DO UPDATE SET payload = excluded.payload',
                       (budget.run_id, budget.model_dump_json()))


def _write_budget(repository: SQLiteStore, connection, budget: RunModelBudgetV1,
                  reservation: RunModelReservationV1, *, event_status: str | None = None) -> None:  # noqa: ANN001
    _save_budget(connection, budget)
    repository._append_agent_run_events(connection, budget.run_id, [('run_model_budget', {
        'invocation_id': reservation.invocation_id, 'request_hash': reservation.request_hash,
        'model_id': reservation.model_id, 'status': event_status or reservation.status,
        'calls': len(budget.reservations), 'accounted_tokens': budget.total_tokens,
        'accounted_output_tokens': budget.output_tokens,
        'usage': reservation.usage.model_dump() if reservation.usage is not None else None,
        'estimation_method': 'utf8_conservative',
        'cost_currency': budget.cost_currency,
        'estimated_cost_micros': budget.estimated_cost_micros,
        'reported_estimated_cost_micros': budget.reported_estimated_cost_micros,
        'unpriced_calls': sum(r.price is None for r in budget.reservations),
        'unknown_usage_calls': sum(r.status == 'unknown' for r in budget.reservations),
        'price_version': reservation.price.version if reservation.price is not None else None,
    })])


def require_tool_execution(connection, run: AgentRun, *, expected_execution_hash: str | None,
                           expected_context: AgentMeshRunContext | None = None) -> None:  # noqa: ANN001
    from agentmesh.skill_runtime.sources import plan_execution_identity, plan_run_execution_identity

    if expected_execution_hash is not None and plan_run_execution_identity(run) != expected_execution_hash:
        raise RunModelBudgetError('run_tool_budget_execution_changed')
    if expected_context is None:
        return
    context = expected_context
    if (context.run_id != run.id or context.plan_id != run.plan_id
        or any(getattr(context, field) != getattr(run, field)
               for field in ('user_id', 'workspace_id', 'project_id', 'thread_id'))):
        raise RunModelBudgetError('run_tool_budget_execution_changed')
    if context.plan_id is None:
        return
    row = connection.execute('SELECT payload FROM skill_plans WHERE id = ?', (context.plan_id,)).fetchone()
    plan = SkillPlan.model_validate_json(row['payload']) if row else None
    node = next((node for node in plan.nodes if node.id == context.node_id), None) if plan else None
    if (plan is None or plan.run_id != run.id or plan.status is not SkillPlanStatus.RUNNING
        or plan.version != context.plan_version or context.plan_execution_hash != plan_execution_identity(plan)
        or node is None or node.status is not SkillPlanNodeStatus.RUNNING or node.attempt != context.node_attempt
        or node.skill_id != context.skill_id):
        raise RunModelBudgetError('run_tool_budget_execution_changed')


def consume_tool_call(repository: SQLiteStore, run_id: str, *, limit: int = 24,
                      expected_execution_hash: str | None = None,
                      expected_context: AgentMeshRunContext | None = None) -> int | None:
    """Keep one ordinary Run counter, governed by the same frozen budget policy."""
    with repository._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        return consume_tool_call_in_transaction(repository, connection, run_id, limit=limit,
            expected_execution_hash=expected_execution_hash, expected_context=expected_context)


def consume_tool_call_in_transaction(repository: SQLiteStore, connection, run_id: str, *, limit: int = 24,
                                     expected_execution_hash: str | None = None,
                                     expected_context: AgentMeshRunContext | None = None) -> int | None:  # noqa: ANN001
    row = connection.execute('SELECT * FROM agent_runs WHERE id = ?', (run_id,)).fetchone()
    if row is None:
        return None
    run = repository._decode_agent_run_row(row)
    if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
        return None
    require_tool_execution(connection, run, expected_execution_hash=expected_execution_hash,
                           expected_context=expected_context)
    if repository._is_retired_research_run(run, row['orchestration_version']) or run.status is not AgentRunStatus.RUNNING:
        return None
    if any(deadline is not None and deadline <= now_utc() for deadline in (run.deadline_at, run.absolute_expires_at)):
        raise RunModelBudgetError('run_tool_budget_deadline_exceeded')
    budget = _read_budget(connection, run_id) or RunModelBudgetV1(run_id=run_id,
        limits=RunModelBudgetLimitsV1.from_env(), price_book=RunModelPriceBookV1.from_env())
    effective_limit = min(limit, budget.limits.max_tool_calls)
    if run.tool_call_count >= effective_limit:
        return None
    run.tool_call_count += 1
    run.updated_at = now_utc()
    connection.execute('UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?',
                       (run.model_dump_json(), run.updated_at.isoformat(), run.id))
    _save_budget(connection, budget)
    repository._append_agent_run_events(connection, run.id, [('run_tool_budget', {
        'calls': run.tool_call_count, 'max_calls': effective_limit,
        'execution_hash': expected_execution_hash,
    })])
    return run.tool_call_count


def reserve_request(repository: SQLiteStore, *, expected_run: AgentRun, limits: RunModelBudgetLimitsV1,
                    reservation: RunModelReservationV1,
                    allowed_statuses: frozenset[AgentRunStatus]) -> RunModelReservationV1:
    with repository._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        return reserve_request_in_transaction(repository, connection, expected_run=expected_run,
            limits=limits, reservation=reservation, allowed_statuses=allowed_statuses)


def reserve_request_in_transaction(repository: SQLiteStore, connection, *, expected_run: AgentRun,
                                   limits: RunModelBudgetLimitsV1, reservation: RunModelReservationV1,
                                   allowed_statuses: frozenset[AgentRunStatus]) -> RunModelReservationV1:  # noqa: ANN001
    from agentmesh.skill_runtime.sources import plan_run_execution_identity

    try:
        reservation = RunModelReservationV1.model_validate(reservation.model_dump())
        limits = RunModelBudgetLimitsV1.model_validate(limits.model_dump())
        if (reservation.status != 'reserved' or reservation.usage is not None or not allowed_statuses
            or not allowed_statuses <= {AgentRunStatus.PLANNING, AgentRunStatus.RUNNING}):
            raise ValueError
    except (TypeError, ValueError) as error:
        raise RunModelBudgetError('run_model_budget_request_invalid') from error
    row = connection.execute('SELECT * FROM agent_runs WHERE id = ?', (expected_run.id,)).fetchone()
    if row is None:
        raise RunModelBudgetError('run_model_budget_run_not_found')
    run = repository._decode_agent_run_row(row)
    if (run.planning_mode is AgentPlanningMode.DEEPSEARCH or run.status not in allowed_statuses
        or plan_run_execution_identity(run) != plan_run_execution_identity(expected_run)
        or reservation.execution_hash != plan_run_execution_identity(expected_run)):
        raise RunModelBudgetError('run_model_budget_execution_changed')
    if any(deadline is not None and deadline <= now_utc()
           for deadline in (run.deadline_at, run.absolute_expires_at)):
        raise RunModelBudgetError('run_model_budget_deadline_exceeded')
    budget = _read_budget(connection, run.id) or RunModelBudgetV1(run_id=run.id, limits=limits,
                                                               price_book=RunModelPriceBookV1.from_env())
    existing = next((r for r in budget.reservations if r.invocation_id == reservation.invocation_id), None)
    if existing is not None:
        if ((reservation.price is not None and reservation.price != existing.price)
            or (reservation.reserved_at is not None and reservation.reserved_at != existing.reserved_at)):
            raise RunModelBudgetError('run_model_budget_invocation_conflict')
        if existing.model_copy(update={'status': 'reserved', 'usage': None, 'price': reservation.price,
                                       'reserved_at': reservation.reserved_at}) != reservation:
            raise RunModelBudgetError('run_model_budget_invocation_conflict')
        return existing
    at = now_utc()
    price = budget.price_book.prices.get(reservation.model_id)
    if price is not None and not price.active_at(at):
        price = None
    if reservation.price is not None or reservation.reserved_at is not None:
        raise RunModelBudgetError('run_model_budget_request_invalid')
    if budget.limits.max_cost_micros is not None:
        if price is None:
            raise RunModelBudgetError('run_model_price_unavailable')
        if price.currency != budget.limits.cost_currency:
            raise RunModelBudgetError('run_model_price_currency_mismatch')
    reservation = reservation.model_copy(update={'price': price, 'reserved_at': at if price is not None else None})
    if sum(r.request_hash == reservation.request_hash for r in budget.reservations) >= budget.limits.max_request_attempts:
        raise RunModelBudgetError('run_model_budget_retry_exhausted')
    updated = budget.model_copy(update={'reservations': [*budget.reservations, reservation]})
    if updated.exhausted:
        raise RunModelBudgetError('run_model_budget_exhausted')
    _write_budget(repository, connection, updated, reservation)
    return reservation


def settle_request(repository: SQLiteStore, *, run_id: str, invocation_id: str,
                   usage: RunModelUsageV1 | None) -> RunModelReservationV1:
    # A late provider receipt settles its original reservation, never Run state.
    # Unknown reservations can later accept real usage; they are never refunded.
    try:
        usage = RunModelUsageV1.model_validate(usage.model_dump()) if usage is not None else None
    except (TypeError, ValueError) as error:
        raise RunModelBudgetError('run_model_budget_settlement_invalid') from error
    with repository._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        budget = _read_budget(connection, run_id)
        existing = next((r for r in budget.reservations if r.invocation_id == invocation_id), None) if budget else None
        if existing is None:
            raise RunModelBudgetError('run_model_budget_reservation_not_found')
        if existing.status == 'settled':
            if usage != existing.usage:
                raise RunModelBudgetError('run_model_budget_settlement_conflict')
            return existing
        settled = existing.model_copy(update={'status': 'settled' if usage is not None else 'unknown', 'usage': usage})
        if settled != existing:
            updated = budget.model_copy(update={'reservations': [settled if r.invocation_id == invocation_id else r
                                                               for r in budget.reservations]})
            _write_budget(repository, connection, updated, settled)
        return settled


def release_unsent_request(repository: SQLiteStore, *, run_id: str, reservation: RunModelReservationV1) -> None:
    """Only the calling adapter's failed admission proves this request was never sent."""
    with repository._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        budget = _read_budget(connection, run_id)
        current = next((r for r in budget.reservations if r.invocation_id == reservation.invocation_id), None) if budget else None
        if current != reservation or current is None or current.status != 'reserved':
            raise RunModelBudgetError('run_model_budget_invocation_conflict')
        updated = budget.model_copy(update={'reservations': [r for r in budget.reservations
                                                            if r.invocation_id != reservation.invocation_id]})
        _write_budget(repository, connection, updated, reservation, event_status='withheld')


class RunModelBudgetMeter:
    """Reserve at the actual local adapter call, then record reported or unknown usage."""

    def __init__(self, repository: SQLiteStore, run: AgentRun, *, model_id: str,
                 allowed_statuses: frozenset[AgentRunStatus] = frozenset({AgentRunStatus.RUNNING}),
                 before_reserve: Callable[[dict], None] | None = None):
        self.repository = repository
        self.run = run.model_copy(deep=True)
        self.model_id = model_id
        self.allowed_statuses = allowed_statuses
        self.limits = RunModelBudgetLimitsV1.from_env()
        self.before_reserve = before_reserve

    def _reserve(self, args: tuple, kwargs: dict) -> RunModelReservationV1:
        from agentmesh.skill_runtime.sources import plan_run_execution_identity

        bound = inspect.signature(Model.get_response).bind(None, *args, **kwargs)
        request = bound.arguments
        if self.before_reserve is not None:
            self.before_reserve({k: v for k, v in request.items() if k != 'self'})
        parts = {k: request[k] for k in ('system_instructions', 'input', 'tools', 'handoffs', 'output_schema', 'model_settings')}
        measured = measure_model_request(**parts, model_id=self.model_id,
                                        budget=ContextRequestBudgetV1(max_tokens=256000, max_output_tokens=32000))
        reservation = RunModelReservationV1(
            invocation_id=new_id('model_request'), request_hash=sha256(json.dumps(
                model_request_payload(**parts), ensure_ascii=False, sort_keys=True,
                separators=(',', ':'), allow_nan=False,
            ).encode('utf-8')).hexdigest(),
            execution_hash=plan_run_execution_identity(self.run), model_id=self.model_id,
            input_token_estimate=measured.estimated_input_tokens, output_token_cap=measured.output_token_cap,
        )
        return self.repository.reserve_run_model_request(expected_run=self.run, limits=self.limits,
            reservation=reservation, allowed_statuses=self.allowed_statuses)

    def _settle(self, reservation: RunModelReservationV1, response: object = None) -> None:
        usage = RunModelUsageV1.from_reported(getattr(response, 'usage', None))
        self.repository.settle_run_model_request(run_id=self.run.id, invocation_id=reservation.invocation_id, usage=usage)
        if usage is not None and (usage.output_tokens > reservation.output_token_cap
                                  or usage.total_tokens > reservation.input_token_estimate + reservation.output_token_cap):
            raise RunModelBudgetError('run_model_request_usage_exceeded')
        if usage is not None and self.repository.get_run_model_budget(self.run.id).exhausted:
            raise RunModelBudgetError('run_model_budget_exhausted')

    def _unknown(self, reservation: RunModelReservationV1, error: BaseException) -> None:
        try:
            self._settle(reservation)
        except Exception:
            error.add_note('run_model_budget_settlement_failed')

    def _prepare(self, args: tuple, kwargs: dict, before_send: Callable | None):  # noqa: ANN202
        reservation = self._reserve(args, kwargs)
        try:
            if before_send is not None:
                kwargs, args = before_send(*args, **kwargs), ()
        except BaseException as error:
            try:
                self.repository.release_unsent_run_model_request(run_id=self.run.id, reservation=reservation)
            except Exception:
                error.add_note('run_model_budget_release_failed')
            raise
        return reservation, args, kwargs

    async def get_response(self, model: Model, *args: Any,
                           before_send: Callable | None = None, **kwargs: Any):  # noqa: ANN202
        reservation, args, kwargs = self._prepare(args, kwargs, before_send)
        try:
            response = await model.get_response(*args, **kwargs)
        except BaseException as error:
            self._unknown(reservation, error)
            raise
        self._settle(reservation, response)
        return response

    async def stream_response(self, model: Model, *args: Any,
                              before_send: Callable | None = None, **kwargs: Any):  # noqa: ANN202
        reservation, args, kwargs = self._prepare(args, kwargs, before_send)
        completed = False
        try:
            async for event in model.stream_response(*args, **kwargs):
                if getattr(event, 'type', None) == 'response.completed':
                    self._settle(reservation, getattr(event, 'response', None))
                    completed = True
                yield event
            if not completed:
                self._settle(reservation)
        except BaseException as error:
            if not completed:
                self._unknown(reservation, error)
            raise
