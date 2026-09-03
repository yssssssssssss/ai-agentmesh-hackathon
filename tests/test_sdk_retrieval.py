from __future__ import annotations

from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agents import PersonalAgent
from agentmesh.models import AgentMemoryBinding, MemoryItem, MemoryLayer, MemoryStatus, Scope, Source, UserMemoryItem
from agentmesh.retrieval import RetrievalProfile, RetrievalService
from agentmesh.seed import TEAM_LEAD, USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.gateway import ToolGateway
from agentmesh.tools import ensure_tool_seed_data


def _repository(tmp_path) -> SQLiteStore:
    repository = SQLiteStore(tmp_path / "retrieval.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    repository.save_user(TEAM_LEAD)
    ensure_tool_seed_data(repository, granted_by="system")
    return repository


def test_retrieval_filters_private_memory_before_ranking(tmp_path) -> None:
    repository = _repository(tmp_path)
    own_source = Source(title="Own source", source_type="note", reference="note://own")
    repository.add_user_memory_item(
        UserMemoryItem(
            id="own_private",
            user_id=USER.id,
            layer=MemoryLayer.MID_TERM,
            title="Checkout evidence",
            summary="checkout address editing issue",
            source_kind="test",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            scope=Scope.PRIVATE,
            sources=[own_source],
        )
    )
    repository.add_user_memory_item(
        UserMemoryItem(
            id="other_private",
            user_id=TEAM_LEAD.id,
            layer=MemoryLayer.MID_TERM,
            title="Other checkout evidence",
            summary="checkout secret address issue",
            source_kind="test",
            workspace_id=TEAM_LEAD.workspace_id,
            project_id=TEAM_LEAD.default_project_id,
            scope=Scope.PRIVATE,
        )
    )
    repository.add_memory_item(
        MemoryItem(
            id="team_checkout",
            title="Accepted checkout evidence",
            summary="checkout address confirmation issue",
            memory_type="finding",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            sources=[Source(title="Team source", source_type="report", reference="report://team")],
        )
    )

    bundle = RetrievalService(repository).retrieve(
        "checkout address",
        user=USER,
        agent_id=USER.personal_agent_id,
        profile=RetrievalProfile(result_types=["memory_item", "user_memory_item"], top_k=10),
    )

    ids = {hit.result.id for hit in bundle.hits}
    assert "own_private" in ids
    assert "team_checkout" in ids
    assert "other_private" not in ids
    assert [hit.citation_label for hit in bundle.hits] == [f"R{index}" for index in range(1, len(bundle.hits) + 1)]


def test_retrieval_honors_memory_type_project_and_result_limit_bindings(tmp_path) -> None:
    repository = _repository(tmp_path)
    for item_id, memory_type in (("finding_one", "finding"), ("finding_two", "finding"), ("decision_one", "decision")):
        repository.add_user_memory_item(
            UserMemoryItem(
                id=item_id,
                user_id=USER.id,
                layer=MemoryLayer.MID_TERM,
                title=f"Bound checkout {item_id}",
                summary="bound checkout evidence",
                source_kind="test",
                memory_type=memory_type,
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
                scope=Scope.PRIVATE,
            )
        )
    binding = AgentMemoryBinding(
        id="binding_retrieval_limits",
        agent_id=USER.personal_agent_id,
        allowed_scopes=[Scope.PRIVATE],
        allowed_memory_types=["finding"],
        allowed_project_ids=[USER.default_project_id],
        max_results_per_query=1,
    )
    repository.save_agent_memory_binding(binding)

    service = RetrievalService(repository)
    bundle = service.retrieve("bound checkout", user=USER, agent_id=USER.personal_agent_id)

    assert len(bundle.hits) == 1
    assert bundle.hits[0].result.id in {"finding_one", "finding_two"}

    repository.save_agent_memory_binding(
        binding.model_copy(update={"allowed_project_ids": ["project_not_allowed"]})
    )
    assert service.retrieve("bound checkout", user=USER, agent_id=USER.personal_agent_id).hits == []


def test_runtime_retrieval_prefilters_candidate_and_disputed_memory_before_ranking_caps(
    tmp_path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    for index in range(225):
        repository.add_memory_item(
            MemoryItem(
                id=f"memory_inactive_hidden_{index:03d}",
                title="Governed runtime memory",
                summary="deprecated memory must stay out of runtime context",
                memory_type="finding",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.DEPRECATED,
                owner_user_id=USER.id,
                workspace_id=USER.workspace_id,
                project_id=USER.default_project_id,
            )
        )
    for item in (
        MemoryItem(
            id="memory_disputed_hidden",
            title="Governed runtime memory",
            summary="disputed must stay out of runtime context",
            memory_type="finding",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.DISPUTED,
            owner_user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
        ),
        MemoryItem(
            id="memory_candidate_hidden",
            title="Governed runtime memory",
            summary="candidate must stay out of runtime context",
            memory_type="finding",
            scope=Scope.TEAM_CANDIDATE,
            status=MemoryStatus.PROPOSED,
            owner_user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
        ),
        MemoryItem(
            id="memory_accepted_visible",
            title="Governed runtime memory",
            summary="accepted team knowledge may enter runtime context",
            memory_type="finding",
            scope=Scope.TEAM_ACCEPTED,
            status=MemoryStatus.ACCEPTED,
            owner_user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
        ),
    ):
        repository.add_memory_item(item)
    profile = RetrievalProfile(
        allowed_scopes=[Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED],
        result_types=["memory_item"],
        top_k=1,
    )

    unfiltered = repository.search(
        "Governed runtime memory",
        {Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED},
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        user_id=USER.id,
        result_types={"memory_item"},
        max_results=1,
        agent_context=False,
    )
    assert unfiltered and unfiltered[0].id != "memory_accepted_visible"

    bundle = RetrievalService(repository).retrieve(
        "Governed runtime memory",
        user=USER,
        agent_id=USER.personal_agent_id,
        profile=profile,
    )
    assert [hit.result.id for hit in bundle.hits] == ["memory_accepted_visible"]

    gateway = ToolGateway(repository)
    monkeypatch.setattr(gateway, "_retrieval_profile", lambda _context, _types: profile)
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_governed_retrieval",
        run_id="run_governed_retrieval",
        skill_id="skill_governed_retrieval",
    )
    payload = gateway.memory_search(context, {"query": "Governed runtime memory"})
    assert [item["id"] for item in payload["results"]] == ["memory_accepted_visible"]


def test_memory_tool_rebinds_visible_sources_to_the_current_run(tmp_path) -> None:
    repository = _repository(tmp_path)
    original = Source(
        id="src_original_memory",
        title="Original memory source",
        source_type="report",
        reference="report://original",
    )
    repository.add_user_memory_item(
        UserMemoryItem(
            id="memory_run_scoped_source",
            user_id=USER.id,
            layer=MemoryLayer.MID_TERM,
            title="Run-scoped checkout evidence",
            summary="run scoped checkout evidence",
            source_kind="test",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            scope=Scope.PRIVATE,
            sources=[original],
        )
    )
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_run_scoped_source",
        run_id="run_scoped_source",
        plan_id="plan_run_scoped_source",
        node_id="node_run_scoped_source",
        skill_id="skill_run_scoped_source",
    )

    payload = ToolGateway(repository).memory_search(context, {"query": "run scoped checkout"})

    returned = payload["results"][0]["sources"][0]
    assert returned["id"] != original.id
    assert returned["workspace_id"] == context.workspace_id
    assert returned["project_id"] == context.project_id
    assert returned["user_id"] == context.user_id
    assert returned["run_id"] == context.run_id
    assert returned["skill_id"] == context.skill_id
    assert repository.get_source(returned["id"]) is not None


def test_pilot_skill_output_is_written_only_to_private_short_term_memory(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path)
    repository = _repository(tmp_path)
    catalog = SkillCatalogService(repository)
    catalog.reload()
    model = ScriptedModel([[assistant_message("JTBD result")]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True, skill_catalog=catalog)
    agent = PersonalAgent(repository, agent_runtime=runtime, skill_catalog=catalog)

    response = agent.handle_chat("$jobs-to-be-done define the checkout job", user=USER)

    assert response.user_memory_items
    item = response.user_memory_items[0]
    assert item.scope == Scope.PRIVATE
    assert item.layer == MemoryLayer.SHORT_TERM
    assert item.source_kind == "sdk_skill:jobs-to-be-done"
    assert not repository.memory_items
