"""Governed enterprise tool implementations exposed through OpenAI Agents SDK."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentmesh.acquisition import AcquisitionRequest
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.data_authorization import authorize_data_query
from agentmesh.datasources import default_data_source_registry
from agentmesh.models import Intent, Scope, User, new_id
from agentmesh.o2 import build_acquisition_agent, maybe_register_o2_data_connector
from agentmesh.retrieval import RetrievalProfile, RetrievalService
from agentmesh.risk import assess_risk_review_with_rules
from agentmesh.store import SQLiteStore


class ToolGateway:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository
        self.acquisition_agent = build_acquisition_agent()
        self.data_registry = default_data_source_registry()
        self.retrieval = RetrievalService(repository)
        maybe_register_o2_data_connector(self.data_registry)

    def handlers(self) -> dict[str, Callable[[AgentMeshRunContext, dict[str, Any]], Any]]:
        return {
            "memory_search": self.memory_search,
            "document_search": self.document_search,
            "data_query": self.data_query,
            "web_research": self.web_research,
            "risk_review": self.risk_review,
        }

    def _user(self, context: AgentMeshRunContext) -> User:
        user = self.repository.get_user(context.user_id)
        if user is None:
            raise ValueError("Runtime user is no longer available")
        return user

    def _retrieval_profile(self, context: AgentMeshRunContext, result_types: list[str]) -> RetrievalProfile:
        run = self.repository.get_agent_run(context.run_id)
        skill = self.repository.get_skill_definition(run.skill_id) if run and run.skill_id else None
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

    def memory_search(self, context: AgentMeshRunContext, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        user = self._user(context)
        bundle = self.retrieval.retrieve(
            query,
            user=user,
            agent_id=user.personal_agent_id,
            profile=self._retrieval_profile(context, ["memory_item", "user_memory_item"]),
            thread_id=context.thread_id,
            task_id=context.run_id,
        )
        return {
            "query": query,
            "results": [
                {
                    "citation": hit.citation_label,
                    "id": hit.result.id,
                    "type": hit.result.result_type,
                    "title": hit.result.title,
                    "summary": hit.result.summary,
                    "scope": hit.result.scope.value,
                    "sources": [source.model_dump(mode="json") for source in hit.result.sources],
                }
                for hit in bundle.hits
            ],
        }

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
                    "sources": [source.model_dump(mode="json") for source in hit.result.sources],
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
        self.repository.add_source(result.source)
        return {
            "title": result.title,
            "connector": result.connector_name,
            "records": result.records,
            "source": result.source.model_dump(mode="json"),
            "metadata": result.metadata,
        }

    def web_research(self, context: AgentMeshRunContext, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        result = self.acquisition_agent.acquire(
            AcquisitionRequest(
                query=query,
                intent=Intent.REQUEST_EXTERNAL_RESEARCH,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                user_id=context.user_id,
                task_id=context.run_id,
                request_post_id=new_id("runtime_request"),
            )
        )
        for source in result.sources:
            self.repository.add_source(source)
        return {
            "title": result.title,
            "content": result.content,
            "sources": [source.model_dump(mode="json") for source in result.sources],
            "permission": result.permission,
            "metadata": result.metadata,
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
