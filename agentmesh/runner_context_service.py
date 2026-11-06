"""Cloud authority for remote model attempts and confirmed context delivery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentmesh.agent_runtime.budget import (
    RunModelBudgetLimitsV1,
    RunModelReservationV1,
    consume_tool_call_in_transaction,
    reserve_request_in_transaction,
)
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_context.contracts import RunContextSnapshotV1
from agentmesh.memory_context.request_budget import ContextRequestBudgetV1
from agentmesh.memory_context.service import MemoryContextError, MemoryContextService
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import AgentRun, AgentRunStatus, SkillDefinition, SkillStatus, User, now_utc
from agentmesh.runner_contracts import (
    RunnerContextReferenceV1,
    RunnerDeliveryAuthorizationV1,
    RunnerExecutionEnvelopeV3,
    RunnerModelDeliveryRequestV1,
    RunnerModelDeliveryResponseV1,
    RunnerModelHandoffRequestV1,
    RunnerSessionSnapshotV1,
    RunnerToolHandoffRequestV1,
    RunnerToolHandoffResponseV1,
    runner_envelope_hash,
)
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.skill_runtime.sources import (
    node_execution_identity,
    plan_execution_identity,
    plan_run_execution_identity,
)
from agentmesh.store import RunnerDispatchConflict, SDKSessionConflict

if TYPE_CHECKING:
    import sqlite3

    from agentmesh.store import SQLiteStore


def _active_run(repository: SQLiteStore, connection: sqlite3.Connection, lease_id: str, runner_id: str) -> AgentRun:
    lease = repository._runner_dispatch_lease_in_transaction(connection, lease_id)
    if lease is None:
        raise RunnerDispatchConflict("runner_lease_not_found")
    require = (
        repository._require_active_runner_node_lease
        if lease.operation_kind == "standard_skill_node"
        else repository._require_active_runner_lease
    )
    _lease, run, _dispatch = require(connection, lease_id=lease_id, runner_id=runner_id, checked_at=now_utc())
    repository._require_run_output_authority(connection, run)
    return run


def _model_policy(repository: SQLiteStore, user: User) -> dict[str, Any]:
    selected = resolve_agent_model_id(repository, user)
    definition = repository.get_model_definition(selected)
    if definition is not None and not definition.enabled:
        raise RunnerDispatchConflict('runner_model_policy_changed')
    return {'agent_id': user.personal_agent_id, 'selected_model_id': selected,
            'definition_hash': canonical_json_sha256(definition.model_dump(
                include={'id', 'provider', 'model_name', 'enabled'})) if definition else None}


def _claim(
    repository: SQLiteStore, connection: sqlite3.Connection, lease_id: str, runner_id: str
) -> tuple[AgentRun, dict[str, Any]]:
    run = _active_run(repository, connection, lease_id, runner_id)
    row = connection.execute(
        "SELECT payload FROM records WHERE collection = 'runner_context_claims' AND id = ?", (lease_id,)
    ).fetchone()
    if row is None:
        raise RunnerDispatchConflict("runner_context_claim_missing")
    claim = json.loads(row["payload"])
    if claim["run_identity_hash"] != plan_run_execution_identity(run):
        raise RunnerDispatchConflict("runner_context_writer_changed")
    if claim.get('model_policy') is not None and claim['model_policy'] != _model_policy(
        repository, repository.get_user(run.user_id),
    ):
        raise RunnerDispatchConflict('runner_model_policy_changed')
    if claim.get("node") is not None:
        plan = repository.get_skill_plan(claim["node"]["plan_id"])
        node = next((node for node in plan.nodes if node.id == claim["node"]["id"]), None) if plan else None
        if (
            plan is None
            or node is None
            or plan_execution_identity(plan) != claim["node"]["plan_hash"]
            or node_execution_identity(node) != claim["node"]["hash"]
            or node.attempt != claim["node"]["attempt"]
        ):
            raise RunnerDispatchConflict("runner_context_node_changed")
    if claim["session"] is not None:
        try:
            record = repository._authorized_sdk_session(connection, run.thread_id, run)
        except SDKSessionConflict as error:
            raise RunnerDispatchConflict(error.code) from error
        snapshot = RunnerSessionSnapshotV1(thread_id=run.thread_id, version=record.version, items=record.items)
        if snapshot.content_hash != claim["session"]["hash"]:
            raise RunnerDispatchConflict("runner_session_snapshot_changed")
    if claim["context"] is not None:
        row = connection.execute(
            "SELECT payload FROM records WHERE collection = 'run_context_snapshots' AND id = ?",
            (claim["context"]["id"],),
        ).fetchone()
        snapshot = RunContextSnapshotV1.model_validate_json(row["payload"]) if row else None
        if (
            snapshot is None
            or snapshot.status != "prepared"
            or snapshot.content_hash != claim["context"]["content_hash"]
        ):
            raise RunnerDispatchConflict("runner_context_snapshot_changed")
    return run, claim


def finish_runner_delivery(
    connection: sqlite3.Connection,
    repository: SQLiteStore,
    authorization: RunnerDeliveryAuthorizationV1,
    receipt_ids: list[str],
) -> None:
    _run, _metadata = _claim(repository, connection, authorization.lease_id, authorization.runner_id)
    delivery = authorization.delivery
    row = connection.execute(
        "SELECT payload FROM records WHERE collection = 'runner_model_handoffs' AND id = ?", (delivery.handoff_id,)
    ).fetchone()
    permit = json.loads(row["payload"]) if row else None
    if (
        permit is None
        or permit["lease_id"] != authorization.lease_id
        or permit["request"]["request_hash"] != delivery.request_hash
    ):
        raise RunnerDispatchConflict("runner_model_handoff_not_found")
    if permit["status"] == "delivered":
        if permit["total_tokens"] != delivery.total_tokens:
            raise RunnerDispatchConflict("runner_model_delivery_conflict")
        return
    permit.update(
        status="delivered",
        receipt_ids=receipt_ids,
        total_tokens=delivery.total_tokens,
        usage=delivery.usage.model_dump() if delivery.usage is not None else None,
    )
    connection.execute(
        "UPDATE records SET payload = ? WHERE collection = 'runner_model_handoffs' AND id = ?",
        (json.dumps(permit), delivery.handoff_id),
    )
    repository._append_agent_run_events(
        connection,
        _run.id,
        [
            (
                "runner_model_delivered",
                {
                    "handoff_id": delivery.handoff_id,
                    "request_hash": delivery.request_hash,
                    "stage": permit["request"]["stage"],
                    "receipt_ids": receipt_ids,
                    "total_tokens": delivery.total_tokens,
                    "context_snapshot_hash": _metadata["context"]["content_hash"] if _metadata["context"] else None,
                },
            )
        ],
    )


def validate_runner_completion(
    connection: sqlite3.Connection,
    repository: SQLiteStore,
    lease_id: str,
    runner_id: str,
) -> None:
    claim = connection.execute(
        "SELECT 1 FROM records WHERE collection = 'runner_context_claims' AND id = ?",
        (lease_id,),
    ).fetchone()
    if claim is None:
        return
    run, metadata = _claim(repository, connection, lease_id, runner_id)
    delivered = connection.execute(
        """SELECT 1 FROM records WHERE collection = 'runner_model_handoffs'
        AND json_extract(payload, '$.lease_id') = ?
        AND json_extract(payload, '$.status') = 'delivered'
        AND json_extract(payload, '$.request.stage') = 'execution' LIMIT 1""",
        (lease_id,),
    ).fetchone()
    if delivered is None:
        raise RunnerDispatchConflict("runner_model_delivery_required")
    if budget_error := runner_budget_error(repository, run.id):
        raise RunnerDispatchConflict(budget_error)
    try:
        RunnerContextService(repository).validate_context(run, metadata)
    except MemoryContextError as error:
        raise RunnerDispatchConflict(error.code) from error


def runner_budget_error(repository: SQLiteStore, run_id: str) -> str | None:
    budget = repository.get_run_model_budget(run_id)
    if budget is None:
        return None
    if any(
        reservation.usage is not None
        and (
            reservation.usage.output_tokens > reservation.output_token_cap
            or reservation.usage.total_tokens > reservation.input_token_estimate + reservation.output_token_cap
        )
        for reservation in budget.reservations
    ):
        return "run_model_request_usage_exceeded"
    return "run_model_budget_exhausted" if budget.exhausted else None


class RunnerContextService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self.memory = MemoryContextService(repository)

    def prepare_direct(
        self, run: AgentRun, user: User, skill: SkillDefinition | None, instructions: str
    ) -> tuple[RunnerContextReferenceV1 | None, str]:
        assembled = self.memory.assemble_for_run(run=run, user=user, query=run.input_text)
        if assembled.core_preferences is None:
            return None, instructions
        context = AgentMeshRunContext(
            user_id=user.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            thread_id=run.thread_id,
            run_id=run.id,
            skill_id=skill.id if skill else None,
        )
        snapshot_id = self.memory.stage_run_snapshot(
            run=run,
            user=user,
            context=context,
            input_text=run.input_text,
            query=run.input_text,
            additional_instructions=assembled.rendered_context,
            bundle=assembled.bundle,
            core_preferences=assembled.core_preferences,
            reason="automatic_run_context",
            skill=skill,
        )
        snapshot = self.memory.load_run_snapshot(snapshot_id, run=run)
        return RunnerContextReferenceV1(
            id=snapshot_id, content_hash=snapshot.content_hash
        ), instructions + assembled.rendered_context

    def node_context(self, run: AgentRun, node_id: str, prompt: dict, instructions: str) -> RunContextSnapshotV1 | None:
        digest = canonical_json_sha256({"input": json.dumps(prompt, ensure_ascii=False)})
        with self.repository._read_connect() as connection:
            rows = connection.execute(
                """SELECT payload FROM records WHERE collection = 'run_context_snapshots'
                AND json_extract(payload, '$.run_id') = ? AND json_extract(payload, '$.node_id') = ?
                AND json_extract(payload, '$.input_hash') = ?""",
                (run.id, node_id, digest),
            ).fetchall()
        for row in rows:
            snapshot = RunContextSnapshotV1.model_validate_json(row["payload"])
            if snapshot.additional_instructions and instructions.endswith(snapshot.additional_instructions):
                return self.memory.load_run_snapshot(snapshot.id, run=run)
        return None

    def bind(self, envelope: RunnerExecutionEnvelopeV3, *, runner_id: str) -> None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = _active_run(self.repository, connection, envelope.lease_id, runner_id)
            policy = _model_policy(self.repository, self.repository.get_user(run.user_id))
            if envelope.model_id != policy['selected_model_id']:
                raise RunnerDispatchConflict('runner_model_policy_changed')
            payload = {
                'model_policy': policy,
                'actual_model_id': None,
                "envelope_hash": envelope.envelope_hash,
                "run_identity_hash": plan_run_execution_identity(run),
                "instructions_hash": canonical_json_sha256({"instructions": envelope.instructions}),
                "input_hash": canonical_json_sha256(
                    {
                        "input": json.dumps(envelope.node_prompt, ensure_ascii=False)
                        if envelope.node_prompt is not None
                        else envelope.input_text
                    }
                ),
                "context": envelope.context.model_dump() if envelope.context else None,
                "session": {"hash": envelope.session.content_hash} if envelope.session else None,
                "tools": [tool.model_dump() for tool in envelope.tools],
                "skill": envelope.skill.model_dump() if envelope.skill else None,
                "node": None,
            }
            if envelope.node_id:
                plan = self.repository.get_skill_plan(envelope.plan_id)
                node = next((node for node in plan.nodes if node.id == envelope.node_id), None) if plan else None
                if plan is None or node is None:
                    raise RunnerDispatchConflict("runner_context_node_changed")
                payload["node"] = {
                    "id": node.id,
                    "plan_id": plan.id,
                    "plan_hash": plan_execution_identity(plan),
                    "hash": node_execution_identity(node),
                    "attempt": node.attempt,
                }
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES ('runner_context_claims', ?, ?)",
                (envelope.lease_id, json.dumps(payload)),
            )

    def validate_context(self, run: AgentRun, claim: dict[str, Any]) -> None:
        self.memory.validate_model_handoff(run)
        if claim["context"] is not None:
            snapshot = self.memory.validate_run_snapshot(claim["context"]["id"], run=run)
            if snapshot.content_hash != claim["context"]["content_hash"]:
                raise MemoryContextError("context_snapshot_invalid")
        user = self.repository.get_user(run.user_id)
        if claim.get("skill"):
            frozen = claim["skill"]
            current = self.repository.get_skill_definition(frozen["id"])
            if current is None or (current.id, current.version, current.content_hash) != (
                frozen["id"],
                frozen["version"],
                frozen["content_hash"],
            ):
                raise RunnerDispatchConflict("context_snapshot_skill_changed")
            bindings = {
                binding.skill_id: binding
                for binding in self.repository.list_agent_skill_bindings(user.personal_agent_id)
            }
            binding = bindings.get(current.id)
            if not SkillCatalogService(self.repository).is_runtime_enabled(
                current,
                binding_enabled=binding is None or binding.enabled,
            ):
                raise RunnerDispatchConflict("context_snapshot_skill_changed")
            owner = current.metadata.get("owner_user_id")
            if owner and current.metadata.get("learned_scope", "private") == "private" and owner != user.id:
                raise RunnerDispatchConflict("context_snapshot_skill_changed")
            learned_id = current.metadata.get("learned_skill_id")
            if learned_id is not None or current.source_path.startswith("learned://"):
                learned = self.repository.get_learned_skill(learned_id or "")
                if (
                    learned is None
                    or learned.status is not SkillStatus.ACTIVE
                    or not self.repository.learned_skill_visible_to_user(learned, user.id, project_id=run.project_id)
                ):
                    raise RunnerDispatchConflict("context_snapshot_skill_changed")
        granted = {
            grant.tool_id for grant in self.repository.list_agent_tool_grants(user.personal_agent_id) if grant.enabled
        }
        available = {
            tool.name: tool for tool in self.repository.tool_definitions if tool.enabled and tool.id in granted
        }
        for frozen in claim["tools"]:
            current = available.get(frozen["name"])
            if (
                current is None
                or current.approval_required
                or current.side_effect != "read"
                or any(
                    getattr(current, key) != frozen[key]
                    for key in ("id", "input_schema", "implementation_id", "implementation_version")
                )
            ):
                raise RunnerDispatchConflict("runner_tool_grant_changed")

    def authorize(self, lease_id: str, runner_id: str, request: RunnerModelHandoffRequestV1) -> str:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run, claim = _claim(self.repository, connection, lease_id, runner_id)
        self.validate_context(run, claim)
        if request.envelope_hash != claim["envelope_hash"]:
            raise RunnerDispatchConflict("runner_context_envelope_changed")
        if request.stage == "execution" and (
            request.instructions_hash != claim["instructions_hash"] or claim["input_hash"] not in request.input_hashes
        ):
            raise RunnerDispatchConflict("runner_context_input_changed")
        budget = (
            ContextRequestBudgetV1(max_tokens=128000, max_output_tokens=2000)
            if request.stage == "compaction"
            else ContextRequestBudgetV1()
        )
        if (
            request.total_chars > budget.max_total_chars
            or request.output_token_cap > budget.max_output_tokens
            or request.estimated_input_tokens + request.output_token_cap > budget.max_tokens
        ):
            raise RunnerDispatchConflict("context_request_budget_exceeded")
        handoff_id = (
            "runner_handoff_"
            + canonical_json_sha256({"lease_id": lease_id, "request_id": request.client_request_id})[:32]
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _run, current_claim = _claim(self.repository, connection, lease_id, runner_id)
            actual_model = current_claim.get('actual_model_id')
            if actual_model is not None and actual_model != request.model_id:
                raise RunnerDispatchConflict('runner_actual_model_changed')
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'runner_model_handoffs' AND id = ?", (handoff_id,)
            ).fetchone()
            if row:
                if json.loads(row["payload"])["request"] != request.model_dump():
                    raise RunnerDispatchConflict("runner_model_handoff_conflict")
            else:
                reserve_request_in_transaction(
                    self.repository,
                    connection,
                    expected_run=run,
                    limits=RunModelBudgetLimitsV1.from_env(),
                    allowed_statuses=frozenset({AgentRunStatus.RUNNING}),
                    reservation=RunModelReservationV1(
                        invocation_id=handoff_id,
                        request_hash=request.request_hash,
                        execution_hash=claim["run_identity_hash"],
                        model_id=request.model_id,
                        input_token_estimate=request.estimated_input_tokens,
                        output_token_cap=request.output_token_cap,
                    ),
                )
                payload = {
                    "run_id": run.id,
                    "lease_id": lease_id,
                    "budget_reservation_id": handoff_id,
                    "request": request.model_dump(),
                    "status": "authorized",
                    "receipt_ids": [],
                    "total_tokens": None,
                }
                connection.execute(
                    "INSERT INTO records(collection, id, payload) VALUES ('runner_model_handoffs', ?, ?)",
                    (handoff_id, json.dumps(payload)),
                )
            if 'actual_model_id' in current_claim and actual_model is None:
                current_claim['actual_model_id'] = request.model_id
                connection.execute("UPDATE records SET payload = ? WHERE collection = 'runner_context_claims' AND id = ?",
                                   (json.dumps(current_claim), lease_id))
        return handoff_id

    def authorize_tool(self, lease_id: str, runner_id: str,
                       request: RunnerToolHandoffRequestV1) -> RunnerToolHandoffResponseV1:
        handoff_id = 'runner_tool_' + canonical_json_sha256(
            {'lease_id': lease_id, 'request_id': request.client_request_id})[:32]
        with self.repository._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            run, claim = _claim(self.repository, connection, lease_id, runner_id)
            self.validate_context(run, claim)
            if request.envelope_hash != claim['envelope_hash']:
                raise RunnerDispatchConflict('runner_context_envelope_changed')
            tool = next((tool for tool in claim['tools'] if tool['name'] == request.tool_name), None)
            if (tool is None or tool['name'] != 'local_file_read'
                    or tool['implementation_id'] != 'runner:local_file_read'
                    or runner_envelope_hash(tool) != request.tool_snapshot_hash):
                raise RunnerDispatchConflict('runner_tool_grant_changed')
            row = connection.execute("SELECT payload FROM records WHERE collection = 'runner_tool_handoffs' AND id = ?",
                                     (handoff_id,)).fetchone()
            if row:
                previous = json.loads(row['payload'])
                if previous['request'] != request.model_dump():
                    raise RunnerDispatchConflict('runner_tool_handoff_conflict')
                return RunnerToolHandoffResponseV1(handoff_id=handoff_id, tool_call_count=previous['tool_call_count'])
            count = consume_tool_call_in_transaction(self.repository, connection, run.id,
                                                     expected_execution_hash=claim['run_identity_hash'])
            if count is None:
                raise RunnerDispatchConflict('run_tool_budget_exhausted')
            payload = {'run_id': run.id, 'lease_id': lease_id, 'request': request.model_dump(), 'tool_call_count': count}
            connection.execute("INSERT INTO records(collection, id, payload) VALUES ('runner_tool_handoffs', ?, ?)",
                               (handoff_id, json.dumps(payload)))
            self.repository._append_agent_run_events(connection, run.id, [('runner_tool_authorized', {
                'handoff_id': handoff_id, 'tool_name': request.tool_name, 'tool_snapshot_hash': request.tool_snapshot_hash,
                'arguments_hash': request.arguments_hash, 'tool_call_hash': request.tool_call_hash,
                'tool_call_count': count,
            })])
        return RunnerToolHandoffResponseV1(handoff_id=handoff_id, tool_call_count=count)

    def confirm(
        self, lease_id: str, runner_id: str, delivery: RunnerModelDeliveryRequestV1
    ) -> RunnerModelDeliveryResponseV1:
        with self.repository._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'runner_model_handoffs' AND id = ?",
                (delivery.handoff_id,),
            ).fetchone()
            permit = json.loads(row["payload"]) if row else None
            lease = self.repository._runner_dispatch_lease_in_transaction(connection, lease_id)
            if (
                permit is None
                or permit["lease_id"] != lease_id
                or lease is None
                or lease.runner_id != runner_id
                or permit["request"]["request_hash"] != delivery.request_hash
            ):
                raise RunnerDispatchConflict("runner_model_handoff_not_found")
            if permit["status"] == "delivered" and (
                permit["total_tokens"] != delivery.total_tokens
                or permit.get("usage") != (delivery.usage.model_dump() if delivery.usage is not None else None)
            ):
                raise RunnerDispatchConflict("runner_model_delivery_conflict")
        if permit.get("budget_reservation_id"):
            # Provider cost belongs to this original attempt even if context was
            # revoked or the Run was cancelled after the actual model response.
            self.repository.settle_run_model_request(
                run_id=permit["run_id"], invocation_id=permit["budget_reservation_id"], usage=delivery.usage
            )
        budget_error = runner_budget_error(self.repository, lease.run_id)
        if permit["status"] == "delivered":
            return RunnerModelDeliveryResponseV1(
                handoff_id=delivery.handoff_id, receipt_ids=permit["receipt_ids"], budget_error_code=budget_error
            )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run, claim = _claim(self.repository, connection, lease_id, runner_id)
        self.validate_context(run, claim)
        authority = RunnerDeliveryAuthorizationV1(lease_id=lease_id, runner_id=runner_id, delivery=delivery)
        snapshot = self.memory.validate_run_snapshot(claim["context"]["id"], run=run) if claim["context"] else None
        if permit["request"]["stage"] == "execution" and snapshot and snapshot.bundle and snapshot.bundle.hits:
            user = self.repository.get_user(run.user_id)
            receipts = self.memory.commit_prepared_for_run(
                snapshot.bundle,
                query=snapshot.query,
                run=run,
                user=user,
                agent_id=user.personal_agent_id,
                reason=snapshot.retrieval_reason,
                runner_delivery=authority,
            ).receipt_ids
        else:
            with self.repository._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                finish_runner_delivery(connection, self.repository, authority, [])
            receipts = []
        return RunnerModelDeliveryResponseV1(
            handoff_id=delivery.handoff_id, receipt_ids=receipts, budget_error_code=budget_error
        )
