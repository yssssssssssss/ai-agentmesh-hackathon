from __future__ import annotations

from pydantic import BaseModel, Field

from agentmesh.models import RetrievalMetrics, Scope, SearchResult, User
from agentmesh.store import SQLiteStore


class RetrievalProfile(BaseModel):
    allowed_scopes: list[Scope] = Field(default_factory=lambda: [Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_ACCEPTED])
    result_types: list[str] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)
    empty_is_fatal: bool = False


class RetrievalHit(BaseModel):
    citation_label: str
    result: SearchResult


class RetrievalBundle(BaseModel):
    query: str
    hits: list[RetrievalHit]
    empty_is_fatal: bool


class RetrievalService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def retrieve(
        self,
        query: str,
        *,
        user: User,
        agent_id: str,
        profile: RetrievalProfile | None = None,
        thread_id: str | None = None,
        task_id: str | None = None,
    ) -> RetrievalBundle:
        selected = profile or RetrievalProfile()
        allowed_scopes = set(selected.allowed_scopes)
        allowed_record_ids: set[str] | None = None
        max_results = selected.top_k
        binding = self.repository.get_binding_for_agent(agent_id)
        if binding is not None:
            allowed_scopes &= set(binding.allowed_scopes or [Scope.PRIVATE])
            max_results = min(max_results, max(1, binding.max_results_per_query))
            if binding.allowed_project_ids and user.default_project_id not in binding.allowed_project_ids:
                allowed_scopes.clear()
            if binding.allowed_memory_types:
                memory_types = set(binding.allowed_memory_types)
                allowed_record_ids = {
                    item.id
                    for item in [*self.repository.memory_items, *self.repository.user_memory_items]
                    if item.memory_type in memory_types
                    and (item.project_id is None or item.project_id == user.default_project_id)
                }
        results = self.repository.search(
            query,
            allowed_scopes,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            user_id=user.id,
            max_results=max_results,
            result_types=set(selected.result_types) if selected.result_types else None,
            allowed_record_ids=allowed_record_ids,
        )
        hits = [RetrievalHit(citation_label=f"R{index}", result=result) for index, result in enumerate(results, 1)]
        self.repository.add_retrieval_metrics(
            RetrievalMetrics(
                query_text=query,
                user_id=user.id,
                results_returned=len(hits),
                source_ids_returned=[source.id for hit in hits for source in hit.result.sources],
                requested_scope="auto",
                task_id=task_id,
                thread_id=thread_id,
            )
        )
        return RetrievalBundle(query=query, hits=hits, empty_is_fatal=selected.empty_is_fatal)
