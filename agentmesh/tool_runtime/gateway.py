"""Governed enterprise tool implementations exposed through OpenAI Agents SDK."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Literal

from agentmesh.acquisition import AcquisitionQuery, AcquisitionRequest
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.data_authorization import authorize_data_query
from agentmesh.datasources import default_data_source_registry
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter, DeepSearchBudgetMutationResult
from agentmesh.deepsearch.tool_policy import DEEPSEARCH_V1_TOOL_NAMES
from agentmesh.memory_context.contracts import MemoryContextBudgetV1, MemoryContextBundleV1
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import (
    AgentRun,
    DeepSearchBudgetUsageV1,
    DeepSearchToolInvocationV1,
    Intent,
    Scope,
    Source,
    ToolDefinition,
    User,
    new_id,
)
from agentmesh.o2 import build_acquisition_agent, maybe_register_o2_data_connector
from agentmesh.retrieval import RetrievalProfile, RetrievalService
from agentmesh.risk import assess_risk_review_with_rules
from agentmesh.store import DeepSearchBudgetConflict, DeepSearchEvidenceConflict, SQLiteStore
from agentmesh.tool_runtime.deepsearch import (
    DeepSearchToolRuntimeError,
    build_deepsearch_tool_invocation,
    normalize_deepsearch_tool_evidence,
)

BUILTIN_TOOL_NAMES = frozenset({"memory_search", "document_search", "data_query", "web_research", "risk_review"})


@dataclass(frozen=True, slots=True)
class PreparedMemoryToolOutput:
    value: dict[str, Any]
    bundle: MemoryContextBundleV1
    query: str
    run: AgentRun
    user: User
    agent_id: str
    reason: str = "tool_memory_search"


@dataclass(frozen=True, slots=True)
class ToolRuntimeDescriptor:
    implementation_id: str
    implementation_version: str
    execution_mode: Literal["real", "fake"]
    health_state: Literal["healthy", "unavailable", "unknown", "stale"]
    health_checked_at: datetime


def collect_source_ids(value: Any) -> set[str]:
    """Collect only structured Source-shaped IDs from governed tool output."""
    if isinstance(value, dict):
        collected: set[str] = set()
        if {"id", "title", "source_type", "reference"}.issubset(value):
            source_id = value.get("id")
            if isinstance(source_id, str) and source_id:
                collected.add(source_id)
        for item in value.values():
            collected.update(collect_source_ids(item))
        return collected
    if isinstance(value, (list, tuple)):
        return {source_id for item in value for source_id in collect_source_ids(item)}
    return set()


class ToolGateway:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self.acquisition_agent = build_acquisition_agent()
        self.data_registry = default_data_source_registry()
        self.retrieval = RetrievalService(repository)
        self.memory_context = MemoryContextService(repository)
        maybe_register_o2_data_connector(self.data_registry)

    def _run_scoped_sources(
        self,
        context: AgentMeshRunContext,
        sources: list[Source],
    ) -> list[Source]:
        scoped: list[Source] = []
        for source in sources:
            source_id = "src_runtime_" + hashlib.sha256(
                f"{context.run_id}:{context.skill_id or ''}:{source.id}:{source.reference}".encode()
            ).hexdigest()[:24]
            scoped_source = source.model_copy(
                update={
                    "id": source_id,
                    "workspace_id": context.workspace_id,
                    "project_id": context.project_id,
                    "user_id": context.user_id,
                    "run_id": context.run_id,
                    "skill_id": context.skill_id,
                }
            )
            scoped.append(self.repository.add_source(scoped_source))
        return scoped

    def handlers(self) -> dict[str, Callable[[AgentMeshRunContext, dict[str, Any]], Any]]:
        handlers = {name: getattr(self, name) for name in BUILTIN_TOOL_NAMES}
        handlers["memory_search"] = self.prepare_memory_search
        return handlers

    def invoke(
        self,
        *,
        context: AgentMeshRunContext,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        invocation: DeepSearchToolInvocationV1 | None = None,
    ) -> Any:
        handler = self.handlers().get(definition.name)
        if handler is None:
            raise ValueError("Tool handler is unavailable")
        if invocation is not None:
            return self._invoke_deepsearch(
                context=context,
                definition=definition,
                arguments=arguments,
                invocation=invocation,
            )
        return handler(context, arguments)

    def _reserve_deepsearch_tool_invocation(
        self,
        *,
        invocation: DeepSearchToolInvocationV1,
        timeout_seconds: float,
    ) -> DeepSearchBudgetMutationResult:
        meter = DeepSearchBudgetMeter(self.repository)
        for _attempt in range(3):
            run = self.repository.get_agent_run(invocation.run_id)
            if run is None or run.deepsearch_budget is None:
                raise DeepSearchToolRuntimeError("deepsearch_tool_persistence_unavailable")
            try:
                return meter.reserve(
                    run_id=invocation.run_id,
                    expected_budget_version=run.deepsearch_budget.version,
                    logical_operation_key=invocation.operation_key,
                    invocation_key=invocation.operation_key,
                    physical_attempt=1,
                    resource_maxima=DeepSearchBudgetUsageV1(
                        active_seconds=timeout_seconds,
                        tool_calls=1,
                    ),
                    tool_invocation=invocation,
                )
            except DeepSearchBudgetConflict as error:
                if error.code == "deepsearch_budget_version_conflict":
                    continue
                raise DeepSearchToolRuntimeError(error.code) from error
        raise DeepSearchToolRuntimeError("deepsearch_budget_version_conflict")

    def _settle_deepsearch_tool_invocation(
        self,
        *,
        invocation: DeepSearchToolInvocationV1,
        active_seconds: float,
    ) -> None:
        meter = DeepSearchBudgetMeter(self.repository)
        actual_usage = DeepSearchBudgetUsageV1(
            active_seconds=active_seconds,
            tool_calls=1,
        )
        for _attempt in range(3):
            run = self.repository.get_agent_run(invocation.run_id)
            if run is None or run.deepsearch_budget is None:
                raise DeepSearchToolRuntimeError("deepsearch_tool_persistence_unavailable")
            try:
                meter.settle(
                    run_id=invocation.run_id,
                    expected_budget_version=run.deepsearch_budget.version,
                    invocation_key=invocation.operation_key,
                    actual_usage=actual_usage,
                )
                return
            except DeepSearchBudgetConflict as error:
                if error.code == "deepsearch_budget_version_conflict":
                    continue
                raise DeepSearchToolRuntimeError(error.code) from error
        raise DeepSearchToolRuntimeError("deepsearch_budget_version_conflict")

    def _invoke_deepsearch(
        self,
        *,
        context: AgentMeshRunContext,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        invocation: DeepSearchToolInvocationV1,
    ) -> dict[str, Any]:
        expected_invocation = build_deepsearch_tool_invocation(
            context=context,
            definition=definition,
            arguments=arguments,
            tool_call_id=invocation.tool_call_id,
        )
        if invocation != expected_invocation:
            raise DeepSearchToolRuntimeError("deepsearch_tool_lineage_mismatch")
        descriptor = self.describe(definition.name)
        if (
            definition.name not in DEEPSEARCH_V1_TOOL_NAMES
            or definition.side_effect != "read"
            or descriptor is None
            or descriptor.implementation_id != invocation.implementation_id
            or descriptor.implementation_version != invocation.implementation_version
            or descriptor.execution_mode != "real"
            or descriptor.health_state != "healthy"
        ):
            raise DeepSearchToolRuntimeError("deepsearch_tool_policy_violation")
        plan = self.repository.get_skill_plan(invocation.plan_id)
        matching_steps = (
            [
                index
                for index, node in enumerate(plan.nodes, start=1)
                if node.id == invocation.node_id
            ]
            if plan is not None
            else []
        )
        if len(matching_steps) != 1 or context.node_step_number != matching_steps[0]:
            raise DeepSearchToolRuntimeError("deepsearch_tool_lineage_mismatch")

        reserved = self._reserve_deepsearch_tool_invocation(
            invocation=invocation,
            timeout_seconds=definition.timeout_seconds,
        )
        if reserved.replayed:
            # The provider outcome may have crossed the process boundary. Never
            # replay a call merely because the SDK invokes the same call ID again.
            raise DeepSearchToolRuntimeError("external_outcome_unknown")

        started = monotonic()
        try:
            value = self.web_research(
                context,
                arguments,
                operation_key=invocation.operation_key,
                persist_sources=False,
            )
        except Exception as error:
            raise DeepSearchToolRuntimeError("external_outcome_unknown") from error
        metadata = value.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("mode") != "real":
            raise DeepSearchToolRuntimeError("deepsearch_tool_execution_not_real")

        batch = normalize_deepsearch_tool_evidence(
            context=context,
            definition=definition,
            invocation=invocation,
            value=value,
            execution_mode="real",
        )
        if batch.sources:
            try:
                persisted = self.repository.save_deepsearch_evidence_batch(
                    invocation=invocation,
                    sources=batch.sources,
                    artifacts=batch.artifacts,
                )
            except DeepSearchEvidenceConflict as error:
                raise DeepSearchToolRuntimeError(error.code) from error
            context.artifact_ids = list(
                dict.fromkeys(
                    [*context.artifact_ids, *(artifact.id for artifact in persisted.artifacts)]
                )
            )
        elapsed = min(max(monotonic() - started, 0.0), definition.timeout_seconds)
        self._settle_deepsearch_tool_invocation(
            invocation=invocation,
            active_seconds=elapsed,
        )

        normalized_value = dict(value)
        normalized_value["sources"] = [
            source.model_dump(mode="json") for source in batch.sources
        ]
        normalized_value["source_evidence"] = [
            item.model_dump(mode="json") for item in batch.source_evidence
        ]
        normalized_value["evidence_bindings"] = [
            {
                "question_ids": list(item.question_ids),
                "success_criterion_ids": [],
                "source_id": item.source_id,
                "evidence_artifact_id": artifact.id,
            }
            for item, artifact in zip(
                batch.source_evidence,
                batch.artifacts,
                strict=True,
            )
        ]
        return normalized_value

    def describe(self, tool_name: str) -> ToolRuntimeDescriptor | None:
        if tool_name not in self.handlers() or tool_name != "web_research":
            return None
        leaves = getattr(self.acquisition_agent, "agents", None)
        agents = list(leaves) if isinstance(leaves, list) else [self.acquisition_agent]
        observations: list[tuple[str, bool, datetime]] = []
        for agent in agents:
            class_name = agent.__class__.__name__
            if class_name == "WebAcquisitionAgent":
                from agentmesh.web_research import web_research_provider_status

                status = web_research_provider_status()
                mode = getattr(getattr(agent, "provider", None), "mode", status.mode)
                observations.append(("real" if mode == "real" else "fake", status.ready, status.checked_at))
            elif class_name == "O2AcquisitionAgent":
                from agentmesh.o2 import o2_research_provider_status

                status = o2_research_provider_status()
                observations.append(("real", status.ready, status.checked_at))
            else:
                observations.append(("fake", False, datetime.now(UTC)))
        real_observations = [item for item in observations if item[0] == "real"]
        execution_mode: Literal["real", "fake"] = "real" if real_observations else "fake"
        candidates = real_observations or observations
        healthy = any(item[1] for item in candidates)
        checked_at = max((item[2] for item in candidates), default=datetime.now(UTC))
        return ToolRuntimeDescriptor(
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode=execution_mode,
            health_state="healthy" if healthy else "unavailable",
            health_checked_at=checked_at,
        )

    def _user(self, context: AgentMeshRunContext) -> User:
        user = self.repository.get_user(context.user_id)
        if user is None:
            raise ValueError("Runtime user is no longer available")
        return user

    def _retrieval_profile(self, context: AgentMeshRunContext, result_types: list[str]) -> RetrievalProfile:
        run = self.repository.get_agent_run(context.run_id)
        skill_id = context.skill_id or (run.skill_id if run else None)
        skill = self.repository.get_skill_definition(skill_id) if skill_id else None
        metadata = skill.metadata if skill else {}
        scope_names = [item.strip() for item in metadata.get("agentmesh-retrieval-scopes", "").split(",") if item.strip()]
        allowed_scopes = []
        for name in scope_names:
            try:
                allowed_scopes.append(Scope(name))
            except ValueError:
                continue
        try:
            top_k = int(metadata.get("agentmesh-top-k", "8"))
        except ValueError:
            top_k = 8
        return RetrievalProfile(
            allowed_scopes=allowed_scopes or [Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_ACCEPTED],
            result_types=result_types,
            top_k=max(1, min(20, top_k)),
            empty_is_fatal=metadata.get("agentmesh-empty-is-fatal", "false").lower() == "true",
        )

    def prepare_memory_search(
        self,
        context: AgentMeshRunContext,
        arguments: dict[str, Any],
    ) -> PreparedMemoryToolOutput:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        user = self._user(context)
        run = self.repository.get_agent_run(context.run_id)
        if run is None:
            raise ValueError("memory_context_run_not_found")
        profile = self._retrieval_profile(context, ["memory_item", "user_memory_item"])
        bundle = self.memory_context.prepare_for_run(
            query,
            run=run,
            user=user,
            agent_id=user.personal_agent_id,
            allowed_scopes=set(profile.allowed_scopes),
            budget=MemoryContextBudgetV1(top_k=min(8, profile.top_k)),
        )
        value = {
            "query": query,
            "results": [
                {
                    "citation": hit.citation_label,
                    "id": hit.memory_id,
                    "type": hit.result.result_type,
                    "title": hit.result.title,
                    "summary": hit.result.summary,
                    "scope": hit.result.scope.value,
                    "sources": [
                        source.model_dump(mode="json")
                        for source in self._run_scoped_sources(context, hit.result.sources)
                    ],
                }
                for hit in bundle.hits
            ],
        }
        return PreparedMemoryToolOutput(
            value=value,
            bundle=bundle,
            query=query,
            run=run,
            user=user,
            agent_id=user.personal_agent_id,
        )

    def commit_memory_search(
        self,
        context: AgentMeshRunContext,
        prepared: PreparedMemoryToolOutput,
    ) -> dict[str, Any]:
        if (
            prepared.run.id != context.run_id
            or prepared.user.id != context.user_id
            or prepared.agent_id != prepared.user.personal_agent_id
        ):
            raise ValueError("memory_context_run_not_found")
        bundle = self.memory_context.commit_prepared_for_run(
            prepared.bundle,
            query=prepared.query,
            run=prepared.run,
            user=prepared.user,
            agent_id=prepared.agent_id,
            reason=prepared.reason,
        )
        context.memory_use_receipt_ids = list(
            dict.fromkeys([*context.memory_use_receipt_ids, *bundle.receipt_ids])
        )
        return prepared.value

    def memory_search(self, context: AgentMeshRunContext, arguments: dict[str, Any]) -> dict[str, Any]:
        prepared = self.prepare_memory_search(context, arguments)
        return self.commit_memory_search(context, prepared)

    def document_search(self, context: AgentMeshRunContext, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        user = self._user(context)
        bundle = self.retrieval.retrieve(
            query,
            user=user,
            agent_id=user.personal_agent_id,
            profile=self._retrieval_profile(context, ["document"]),
            thread_id=context.thread_id,
            task_id=context.run_id,
        )
        return {
            "query": query,
            "results": [
                {
                    "citation": hit.citation_label,
                    "id": hit.result.id,
                    "title": hit.result.title,
                    "summary": hit.result.summary,
                    "sources": [
                        source.model_dump(mode="json")
                        for source in self._run_scoped_sources(context, hit.result.sources)
                    ],
                }
                for hit in bundle.hits
            ],
        }

    def data_query(self, context: AgentMeshRunContext, arguments: dict[str, Any]) -> dict[str, Any]:
        user = self._user(context)
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        authorize_data_query(self.repository, user, "auto", "query")
        result = self.data_registry.query_first_available(
            connector_names=["http_data_api", "o2_cli", "local_metrics"],
            operation="query",
            parameters={"query": query, "metric": query, "limit": 5},
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            requested_by=context.user_id,
        )
        source = result.source.model_copy(
            update={
                "workspace_id": context.workspace_id,
                "project_id": context.project_id,
                "user_id": context.user_id,
                "run_id": context.run_id,
                "skill_id": context.skill_id,
            }
        )
        self.repository.add_source(source)
        return {
            "title": result.title,
            "connector": result.connector_name,
            "records": result.records,
            "source": source.model_dump(mode="json"),
            "metadata": result.metadata,
        }

    def web_research(
        self,
        context: AgentMeshRunContext,
        arguments: dict[str, Any],
        *,
        operation_key: str | None = None,
        persist_sources: bool = True,
    ) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        raw_question_queries = arguments.get("question_queries", [])
        if not isinstance(raw_question_queries, list):
            raise ValueError("question_queries must be a list")
        try:
            question_queries = [AcquisitionQuery.model_validate(item) for item in raw_question_queries]
        except (TypeError, ValueError):
            raise ValueError("question_queries are invalid") from None
        result = self.acquisition_agent.acquire(
            AcquisitionRequest(
                query=query,
                question_queries=question_queries,
                intent=Intent.REQUEST_EXTERNAL_RESEARCH,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                user_id=context.user_id,
                task_id=context.run_id,
                request_post_id=(
                    f"research_operation_{operation_key}"
                    if operation_key is not None
                    else new_id("runtime_request")
                ),
            )
        )
        sources = [
            source.model_copy(
                update={
                    "workspace_id": context.workspace_id,
                    "project_id": context.project_id,
                    "user_id": context.user_id,
                    "run_id": context.run_id,
                    "skill_id": context.skill_id,
                }
            )
            for source in result.sources
        ]
        if persist_sources:
            for source in sources:
                self.repository.add_source(source)
        return {
            "title": result.title,
            "content": result.content,
            "sources": [source.model_dump(mode="json") for source in sources],
            "source_evidence": [item.model_dump(mode="json") for item in result.source_evidence],
            "provider_calls": [item.model_dump(mode="json") for item in result.provider_calls],
            "permission": result.permission,
            "metadata": {
                **result.metadata,
                **({"operation_key": operation_key} if operation_key is not None else {}),
            },
        }

    def risk_review(self, context: AgentMeshRunContext, arguments: dict[str, Any]) -> dict[str, Any]:
        del context
        content = str(arguments.get("content") or "").strip()
        if not content:
            raise ValueError("content is required")
        assessment = assess_risk_review_with_rules(content, self.repository.risk_policy_rules)
        return assessment.model_dump(mode="json")


def encode_tool_output(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
