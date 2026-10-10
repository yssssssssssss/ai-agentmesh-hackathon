import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from agentmesh.memory_facts import MemoryFactsService, document_evidence_hash
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.memory_learning.contracts import DocumentSourceSpanV1
from agentmesh.memory_learning.service import source_span_hash
from agentmesh.memory_payloads import FactAssertionV1, FactRememberV1
from agentmesh.memory_relations import (
    MemoryRelationCreateV1,
    MemoryRelationError,
    MemoryRelationQueryV1,
    MemoryRelationService,
    RelationLookupV1,
)
from agentmesh.models import (
    ChatThreadKind,
    DocumentRecord,
    MemoryItem,
    MemoryLayer,
    PermissionPolicyRule,
    Project,
    Scope,
    Source,
    User,
    UserMemoryItem,
    now_utc,
)
from agentmesh.seed import PROJECT, USER
from agentmesh.store import SQLiteStore, store
from agentmesh.task_management.contracts import TaskArchiveRequest, TaskCreateRequest, TaskTransitionRequest
from agentmesh.task_management.service import TaskManagementService
from tests.test_chat_flow import authenticated_client, clear_store
from tests.test_memory_governance import _accepted_team_memory


def test_task_graph_expands_reviewed_memory_and_its_sealed_evidence_within_two_hops(monkeypatch):
    clear_store()
    owner, _reviewer, task, memory = _accepted_team_memory(monkeypatch, "relation-graph")
    task = task["task"]
    response = owner.post(
        "/api/memory/relations/query",
        json={
            "project_id": PROJECT.id,
            "root": {"record_type": "task", "record_id": task["id"]},
            "max_hops": 2,
        },
    )
    assert response.status_code == 200, response.text
    graph = response.json()
    assert graph["data_mode"] == "real"
    assert graph["root_key"] == f"task:{task['id']}"
    assert any(node["record_type"] == "memory_item" and node["record_id"] == memory["id"] for node in graph["nodes"])
    assert any(node["record_type"] == "artifact" for node in graph["nodes"])
    assert {edge["relation_type"] for edge in graph["edges"]} >= {
        "derived_from_task_review",
        "derived_from_artifact",
    }
    assert all(node["depth"] <= 2 and "summary" not in node and "content" not in node for node in graph["nodes"])


def _query(client, kind, record_id, **limits):
    return client.post(
        "/api/memory/relations/query",
        json={
            "project_id": PROJECT.id,
            "root": {"record_type": kind, "record_id": record_id},
            **limits,
        },
    )


def _reference(node):
    return {key: node[key] for key in ("record_type", "record_id", "version", "content_hash")}


def test_controlled_relation_freezes_current_endpoints_and_evidence_and_is_a_candidate_by_default(monkeypatch):
    clear_store()
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    client = authenticated_client()
    task = client.post("/api/tasks", json={"command_id": "relation-task", "title": "Rollout gate"}).json()["item"][
        "task"
    ]
    memory = store.add_user_memory_item(
        UserMemoryItem(
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            layer=MemoryLayer.LONG_TERM,
            source_kind="promoted",
            title="Rollout decision",
            summary="Check acceptance first",
        )
    )
    source = _query(client, "user_memory_item", memory.id).json()["nodes"][0]
    target = _query(client, "task", task["id"]).json()["nodes"][0]
    payload = {
        "project_id": PROJECT.id,
        "command_id": "relation-create",
        "source": _reference(source),
        "target": _reference(target),
        "evidence": _reference(target),
        "relation_type": "supports",
    }
    created = client.post("/api/memory/relations", json=payload)
    assert created.status_code == 201, created.text
    relation = created.json()
    assert relation["assertion"] == "candidate"
    assert relation["source_version"] == source["version"]
    assert relation["source_hash"] == source["content_hash"]
    assert relation["target_version"] == target["version"]
    assert relation["evidence_hash"] == target["content_hash"]
    assert client.post("/api/memory/relations", json=payload).json() == relation
    graph = _query(client, "task", task["id"]).json()
    assert any(edge["id"] == relation["id"] and edge["assertion"] == "candidate" for edge in graph["edges"])


@pytest.fixture
def relation_project(tmp_path):
    repository = SQLiteStore(tmp_path / "relations.sqlite3")
    owner = repository.save_user(
        User(
            id="owner",
            workspace_id="ws",
            default_project_id="project",
            name="Owner",
            role="user",
            personal_agent_id="owner-agent",
        )
    )
    peer = repository.save_user(owner.model_copy(update={"id": "peer", "personal_agent_id": "peer-agent"}))
    repository.save_project(
        Project(
            id="project", workspace_id="ws", name="Project", goal="Current relations", member_ids=[owner.id, peer.id]
        )
    )
    source = Source(
        id="source",
        title="Assignments",
        source_type="document",
        reference="local://assignments",
        workspace_id="ws",
        project_id="project",
        user_id=owner.id,
    )
    document = repository.add_document(
        DocumentRecord(
            id="doc",
            title="Assignments",
            file_name="assignment.txt",
            content_type="text/plain",
            text="Bob owns rollout.",
            source=source,
            workspace_id="ws",
            project_id="project",
            uploaded_by=owner.id,
        )
    )
    memory = repository.add_user_memory_item(
        UserMemoryItem(
            id="memory",
            user_id=owner.id,
            workspace_id="ws",
            project_id="project",
            layer=MemoryLayer.LONG_TERM,
            source_kind="promoted",
            title="Rollout gate",
            summary="Verify acceptance.",
        )
    )
    yield repository, owner, peer, document, memory, MemoryRelationService(repository)
    repository.close()


def _graph(service, owner, kind, record_id, **limits):
    return service.query(
        MemoryRelationQueryV1(
            project_id="project", root=RelationLookupV1(record_type=kind, record_id=record_id), **limits
        ),
        owner,
    )


def test_frozen_document_fact_citation_requires_current_body_even_without_version_change(relation_project):
    repository, owner, _, document, _, service = relation_project
    item = MemoryFactsService(repository).remember(
        FactRememberV1(
            command_id="remember",
            project_id="project",
            title="Rollout owner",
            summary="Bob is the owner",
            source_document_id=document.id,
            source_version=document.version,
            source_hash=document_evidence_hash(document),
            facts=[
                FactAssertionV1(
                    subject_type="project",
                    subject_id="project",
                    predicate="owner",
                    value="Bob",
                    time_precision="unknown",
                )
            ],
        ),
        owner,
    )
    graph = _graph(service, owner, "user_memory_item", item.id)
    assert [(edge.relation_type, edge.to_key) for edge in graph.edges] == [("cites", "document:doc")]
    assert graph.edges[0].evidence.content_hash == document_evidence_hash(document)
    assert graph.nodes[1].navigation_href == "/knowledge?project=project&document=doc"
    assert _graph(service, owner, "document", document.id).edges == graph.edges
    document.text = "Alice owns rollout."
    repository.save_document(document)
    assert _graph(service, owner, "user_memory_item", item.id).edges == []


def _relation_request(fixture, *, command="relate", source=None, target=None, assertion="candidate"):
    _, owner, _, document, memory, service = fixture
    source_node = _graph(service, owner, *(source or ("user_memory_item", memory.id))).nodes[0]
    target_node = _graph(service, owner, *(target or ("document", document.id))).nodes[0]
    evidence_node = _graph(service, owner, "document", document.id).nodes[0]
    return MemoryRelationCreateV1(
        project_id="project",
        command_id=command,
        source=_reference(source_node.model_dump()),
        target=_reference(target_node.model_dump()),
        evidence=_reference(evidence_node.model_dump()),
        relation_type="supports",
        assertion=assertion,
    )


@pytest.mark.parametrize("change", ["source_body", "source_version", "document_body", "document_version"])
def test_stale_snapshot_cannot_create_or_replay_a_relation_and_is_not_expanded(relation_project, change):
    repository, owner, _, document, memory, service = relation_project
    request = _relation_request(relation_project)
    created = service.create(request, owner)
    assert created.id in {edge.id for edge in _graph(service, owner, "user_memory_item", memory.id).edges}
    if change.startswith("source"):
        memory.summary = "Changed" if change.endswith("body") else memory.summary
        memory.version += int(change.endswith("version"))
        repository.save_user_memory_item(memory)
    else:
        document.text = "Changed" if change.endswith("body") else document.text
        document.version += int(change.endswith("version"))
        repository.save_document(document)
    assert _graph(service, owner, "user_memory_item", memory.id).edges == []
    with pytest.raises(MemoryRelationError, match="relation_endpoint_changed"):
        service.create(request, owner)


@pytest.mark.parametrize("change", ["disabled", "workspace", "membership", "project_archived"])
def test_query_and_write_reload_current_actor_and_project(relation_project, change):
    repository, owner, _, _, memory, service = relation_project
    request = _relation_request(relation_project)
    if change in {"disabled", "workspace"}:
        repository.save_user(
            owner.model_copy(update={"status": "disabled"} if change == "disabled" else {"workspace_id": "foreign"})
        )
    else:
        project = repository.get_project("project")
        repository.save_project(
            project.model_copy(update={"member_ids": ["peer"]} if change == "membership" else {"status": "archived"})
        )
    for operation in (
        lambda: _graph(service, owner, "user_memory_item", memory.id),
        lambda: service.create(request, owner),
    ):
        with pytest.raises(MemoryRelationError):
            operation()


def test_private_memory_and_document_remain_private_even_to_current_admin(relation_project):
    repository, owner, peer, document, memory, service = relation_project
    peer = repository.save_user(peer.model_copy(update={"role": "admin"}))
    request = _relation_request(relation_project)
    service.create(request, owner)
    for kind, record_id in (("user_memory_item", memory.id), ("document", document.id)):
        with pytest.raises(MemoryRelationError, match="relation_root_not_found"):
            _graph(service, peer, kind, record_id)
    with pytest.raises(MemoryRelationError, match="relation_endpoint_not_found"):
        service.create(request, peer)


def test_task_graph_follows_children_and_dependencies_in_both_directions_without_a_third_hop(
    relation_project, monkeypatch
):
    repository, owner, _, _, _, service = relation_project
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    owner = repository.save_user(owner.model_copy(update={"role": "team_lead"}))
    tasks = TaskManagementService(repository)
    parent = tasks.create_task(TaskCreateRequest(command_id="parent", title="Parent"), owner).task
    child = tasks.create_task(
        TaskCreateRequest(command_id="child", title="Child", parent_task_id=parent.id), owner
    ).task
    grandchild = tasks.create_task(
        TaskCreateRequest(command_id="grandchild", title="Grandchild", parent_task_id=child.id), owner
    ).task
    last = tasks.create_task(
        TaskCreateRequest(command_id="last", title="Last", parent_task_id=grandchild.id), owner
    ).task
    dependent = tasks.create_task(
        TaskCreateRequest(command_id="dependent", title="Dependent", dependency_task_ids=[parent.id]), owner
    ).task
    graph = _graph(service, owner, "task", parent.id)
    assert {node.record_id for node in graph.nodes} == {parent.id, child.id, grandchild.id, dependent.id}
    assert last.id not in {node.record_id for node in graph.nodes}
    assert any(
        edge.from_key == f"task:{dependent.id}"
        and edge.to_key == f"task:{parent.id}"
        and edge.relation_type == "depends_on"
        for edge in graph.edges
    )
    assert _graph(service, owner, "task", parent.id, max_hops=1).nodes[-1].depth == 1


def test_personal_share_parent_is_frozen_and_only_expands_for_its_owner(relation_project):
    repository, owner, peer, _, memory, service = relation_project
    shared = repository.add_memory_item(
        MemoryItem(
            title="Shared lesson",
            summary="Reviewed lesson",
            memory_type="method",
            status="accepted",
            scope=Scope.PROJECT,
            owner_user_id=owner.id,
            workspace_id="ws",
            project_id="project",
            metadata={
                "source_memory_id": memory.id,
                "source_memory_version": str(memory.version),
                "source_memory_hash": memory_content_hash(memory),
            },
        )
    )
    graph = _graph(service, owner, "memory_item", shared.id)
    assert [(edge.relation_type, edge.to_key) for edge in graph.edges] == [
        ("shared_from_personal", "user_memory_item:memory")
    ]
    peer_graph = _graph(service, peer, "memory_item", shared.id)
    assert len(peer_graph.nodes) == 1 and peer_graph.edges == []
    assert all(node.record_id != memory.id for node in peer_graph.nodes)
    assert "user_memory_item:memory" not in peer_graph.model_dump_json()
    memory.summary = "Changed private body"
    repository.save_user_memory_item(memory)
    assert _graph(service, owner, "memory_item", shared.id).edges == []


def test_hidden_relation_fanout_cannot_consume_visible_candidate_budget_or_leak_titles(relation_project):
    repository, owner, peer, document, memory, service = relation_project
    visible = service.create(_relation_request(relation_project), owner)
    hidden = repository.add_user_memory_item(
        memory.model_copy(update={"id": "secret", "user_id": peer.id, "title": "PRIVATE TITLE"})
    )
    for index in range(150):
        repository.add_memory_relation(
            visible.model_copy(
                update={
                    "id": f"hidden-{index}",
                    "created_by": peer.id,
                    "from_memory_id": hidden.id,
                    "source_hash": memory_content_hash(hidden),
                }
            )
        )
    graph = _graph(service, owner, "document", document.id)
    assert [edge.id for edge in graph.edges] == [visible.id]
    assert graph.truncated is False
    assert "PRIVATE TITLE" not in graph.model_dump_json() and "secret" not in graph.model_dump_json()


def test_separately_private_evidence_withholds_an_otherwise_visible_relation(relation_project):
    repository, owner, peer, document, _, service = relation_project
    relation = service.create(_relation_request(relation_project), owner)
    private_doc = repository.add_document(
        document.model_copy(update={"id": "private-proof", "uploaded_by": peer.id, "title": "PRIVATE PROOF"})
    )
    repository.add_memory_relation(
        relation.model_copy(
            update={"evidence_id": private_doc.id, "evidence_hash": document_evidence_hash(private_doc)}
        )
    )
    graph = _graph(service, owner, "document", document.id)
    assert graph.edges == [] and graph.truncated is False
    assert "private-proof" not in graph.model_dump_json() and "PRIVATE PROOF" not in graph.model_dump_json()


def test_relation_audit_failure_rolls_back_and_retry_is_durable_once(relation_project):
    repository, owner, _, _, memory, service = relation_project
    request = _relation_request(relation_project)
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_relation_audit BEFORE INSERT ON records
            WHEN NEW.collection='audit_events' AND json_extract(NEW.payload,'$.action')='create_memory_relation'
            BEGIN SELECT RAISE(ABORT,'audit fault'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="audit fault"):
        service.create(request, owner)
    assert _graph(service, owner, "user_memory_item", memory.id).edges == []
    with repository._connect() as connection:
        connection.execute("DROP TRIGGER reject_relation_audit")
    created = service.create(request, owner)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert {result.id for result in pool.map(lambda _: service.create(request, owner), range(4))} == {created.id}
    reopened = SQLiteStore(repository.db_path)
    try:
        assert MemoryRelationService(reopened).create(request, owner).id == created.id
        assert [
            edge.id for edge in _graph(MemoryRelationService(reopened), owner, "user_memory_item", memory.id).edges
        ] == [created.id]
        with reopened._read_connect() as connection:
            assert (
                connection.execute(
                    "SELECT count(*) FROM records WHERE collection='audit_events' AND json_extract(payload,'$.action')='create_memory_relation'"
                ).fetchone()[0]
                == 1
            )
    finally:
        reopened.close()


def test_command_conflict_does_not_silently_confirm_a_candidate(relation_project):
    _, owner, _, _, memory, service = relation_project
    request = _relation_request(relation_project)
    original = service.create(request, owner)
    with pytest.raises(MemoryRelationError, match="relation_command_conflict"):
        service.create(request.model_copy(update={"assertion": "confirmed"}), owner)
    graph = _graph(service, owner, "user_memory_item", memory.id)
    assert graph.edges[0].id == original.id and graph.edges[0].assertion == "candidate"
    confirmed = service.create(
        request.model_copy(update={"command_id": "human-confirmed", "assertion": "confirmed"}), owner
    )
    assert confirmed.assertion == "confirmed"


@pytest.mark.parametrize("withdraw", ["memory", "document"])
def test_archived_memory_or_withdrawn_evidence_removes_current_edges(relation_project, withdraw):
    repository, owner, _, document, memory, service = relation_project
    request = _relation_request(relation_project)
    service.create(request, owner)
    if withdraw == "memory":
        memory.status, memory.archived_at = "archived", now_utc()
        repository.save_user_memory_item(memory)
        graph = _graph(service, owner, "document", document.id)
    else:
        document.withdrawn_at = now_utc()
        repository.save_document(document)
        graph = _graph(service, owner, "user_memory_item", memory.id)
    assert graph.edges == []
    with pytest.raises(MemoryRelationError, match="relation_endpoint_not_found"):
        service.create(request, owner)


def test_cycles_and_visible_output_budgets_remain_bounded(relation_project):
    repository, owner, _, _, memory, service = relation_project
    items = [
        memory,
        *[repository.add_user_memory_item(memory.model_copy(update={"id": f"memory-{index}"})) for index in range(2)],
    ]
    for index, item in enumerate(items):
        request = _relation_request(
            relation_project,
            command=f"cycle-{index}",
            source=("user_memory_item", item.id),
            target=("user_memory_item", items[(index + 1) % 3].id),
        )
        service.create(request, owner)
    graph = _graph(service, owner, "user_memory_item", memory.id)
    assert len(graph.nodes) == 3 and len(graph.edges) == 3
    assert len({node.key for node in graph.nodes}) == len(graph.nodes)
    assert all(node.depth <= 2 for node in graph.nodes)
    for limits, diagnostic in (({"max_nodes": 1}, "node_limit"), ({"max_edges": 1}, "edge_limit")):
        bounded = _graph(service, owner, "user_memory_item", memory.id, **limits)
        assert diagnostic in bounded.diagnostics and bounded.truncated is True
        assert len(bounded.nodes) <= limits.get("max_nodes", 40)
        assert len(bounded.edges) <= limits.get("max_edges", 80)


def test_output_character_and_candidate_budgets_report_only_visible_truncation(relation_project):
    repository, owner, _, _, memory, service = relation_project
    relation = service.create(_relation_request(relation_project), owner)
    for index in range(140):
        target = repository.add_user_memory_item(
            memory.model_copy(update={"id": f"visible-{index}", "title": "标题" * 60})
        )
        repository.add_memory_relation(
            relation.model_copy(
                update={
                    "id": f"relation-{index}",
                    "to_source_id": target.id,
                    "target_record_type": "user_memory_item",
                    "target_version": target.version,
                    "target_hash": memory_content_hash(target),
                }
            )
        )
    graph = _graph(service, owner, "user_memory_item", memory.id, max_chars=4096)
    assert len(graph.model_dump_json()) <= 4096
    assert {"candidate_limit", "output_limit"} <= set(graph.diagnostics)
    assert graph.truncated


def test_oversized_private_root_is_not_decoded_or_returned(relation_project):
    repository, owner, _, _, memory, service = relation_project
    repository.save_user_memory_item(memory.model_copy(update={"summary": "x" * 65536}))
    with pytest.raises(MemoryRelationError, match="relation_root_not_found"):
        _graph(service, owner, "user_memory_item", memory.id)


def test_private_record_id_collision_does_not_hide_a_reviewed_shared_memory(monkeypatch):
    clear_store()
    owner, _, task, memory = _accepted_team_memory(monkeypatch, "collision")
    store.add_user_memory_item(
        UserMemoryItem(
            id=memory["id"],
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=PROJECT.id,
            layer=MemoryLayer.LONG_TERM,
            source_kind="promoted",
            title="Unverified record",
            summary="Not reviewed",
            provenance={**memory["provenance"], "review_id": "missing-review"},
        )
    )
    graph = _query(owner, "task", task["task"]["id"]).json()
    assert any(node["record_type"] == "memory_item" and node["record_id"] == memory["id"] for node in graph["nodes"])
    assert not any(
        node["record_type"] == "user_memory_item" and node["record_id"] == memory["id"] for node in graph["nodes"]
    )


def test_write_waiting_for_the_database_lock_reloads_revoked_authority(relation_project):
    repository, owner, _, _, memory, service = relation_project
    request = _relation_request(relation_project)
    started = Event()

    def create():
        started.set()
        return service.create(request, owner)

    with repository._connect() as connection, ThreadPoolExecutor(max_workers=1) as pool:
        connection.execute("BEGIN IMMEDIATE")
        future = pool.submit(create)
        assert started.wait(2)
        connection.execute(
            "UPDATE records SET payload=? WHERE collection='users' AND id=?",
            (owner.model_copy(update={"status": "disabled"}).model_dump_json(), owner.id),
        )
        connection.commit()
        with pytest.raises(MemoryRelationError, match="relation_actor_not_authorized"):
            future.result(timeout=5)
    repository.save_user(owner)
    assert _graph(service, owner, "user_memory_item", memory.id).edges == []


def test_shared_memory_annotation_requires_current_management_permission(relation_project):
    repository, owner, peer, document, _, service = relation_project
    shared = repository.add_memory_item(
        MemoryItem(
            title="Shared",
            summary="Current",
            memory_type="method",
            status="accepted",
            scope=Scope.PROJECT,
            owner_user_id=peer.id,
            workspace_id="ws",
            project_id="project",
        )
    )
    request = _relation_request(relation_project, source=("memory_item", shared.id))
    with pytest.raises(MemoryRelationError, match="relation_source_write_denied"):
        service.create(request, owner)
    manager = repository.save_user(owner.model_copy(update={"role": "team_lead"}))
    created = service.create(request, manager)
    repository.save_permission_policy_rule(
        PermissionPolicyRule(role="team_lead", action="manage_team_memory", effect="deny")
    )
    with pytest.raises(MemoryRelationError, match="relation_source_write_denied"):
        service.create(request, manager)
    assert created.id in {edge.id for edge in _graph(service, manager, "document", document.id).edges}


def test_permission_rules_follow_existing_creation_order_instead_of_lexical_record_ids(relation_project):
    repository, owner, peer, _, _, service = relation_project
    repository.save_user(owner.model_copy(update={"role": "team_lead"}))
    shared = repository.add_memory_item(
        MemoryItem(
            title="Shared",
            summary="Current",
            memory_type="method",
            status="accepted",
            scope=Scope.PROJECT,
            owner_user_id=peer.id,
            workspace_id="ws",
            project_id="project",
        )
    )
    repository.save_permission_policy_rule(
        PermissionPolicyRule(id="z-first", role="team_lead", action="manage_team_memory", effect="deny")
    )
    repository.save_permission_policy_rule(
        PermissionPolicyRule(id="a-second", role="team_lead", action="manage_team_memory", effect="allow")
    )
    created = service.create(_relation_request(relation_project, source=("memory_item", shared.id)), owner)
    assert created.created_by == owner.id


@pytest.mark.parametrize("relation_type", ["relates_to", "supports", "contradicts", "supersedes", "caused_by"])
def test_five_controlled_types_are_annotations_and_never_change_memory_lifecycle(relation_project, relation_type):
    repository, owner, _, _, memory, service = relation_project
    request = _relation_request(relation_project).model_copy(update={"relation_type": relation_type})
    created = service.create(request, owner)
    assert created.relation_type == relation_type
    assert repository.get_user_memory_item(memory.id).model_dump() == memory.model_dump()
    assert _graph(service, owner, "user_memory_item", memory.id).edges[0].assertion == "candidate"


@pytest.mark.parametrize("root_change", ["conversation", "foreign_project", "archived"])
def test_private_foreign_and_archived_tasks_cannot_be_graph_roots(relation_project, monkeypatch, root_change):
    repository, owner, _, _, _, service = relation_project
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    task = TaskManagementService(repository).create_task(TaskCreateRequest(command_id="task", title="Task"), owner).task
    if root_change == "archived":
        owner = repository.save_user(owner.model_copy(update={"role": "team_lead"}))
        tasks = TaskManagementService(repository)
        cancelled = tasks.transition_task(
            task.id, TaskTransitionRequest(command_id="cancel", expected_version=1, action="cancel"), owner
        )
        tasks.archive_task(
            task.id, TaskArchiveRequest(command_id="archive", expected_version=cancelled.management.version), owner
        )
    else:
        thread = repository.get_chat_thread(task.thread_id)
        repository.save_chat_thread(
            thread.model_copy(
                update={"kind": ChatThreadKind.CONVERSATION}
                if root_change == "conversation"
                else {"project_id": "foreign"}
            )
        )
    with pytest.raises(MemoryRelationError, match="relation_root_not_found"):
        _graph(service, owner, "task", task.id)


def test_frozen_literal_source_span_citation_is_checked_in_both_directions(relation_project):
    repository, owner, _, document, memory, service = relation_project
    item = MemoryFactsService(repository).remember(
        FactRememberV1(
            command_id="fact-span",
            project_id="project",
            title="Rollout owner",
            summary="Bob",
            source_document_id=document.id,
            source_version=document.version,
            source_hash=document_evidence_hash(document),
            facts=[
                FactAssertionV1(
                    subject_type="project",
                    subject_id="project",
                    predicate="owner",
                    value="Bob",
                    time_precision="unknown",
                )
            ],
        ),
        owner,
    )
    span = DocumentSourceSpanV1(
        id="span",
        document_id=document.id,
        source_id=document.source.id,
        source_version=document.version,
        source_hash=document_evidence_hash(document),
        workspace_id="ws",
        project_id="project",
        user_id=owner.id,
        start=0,
        end=3,
        quote="Bob",
        created_at=now_utc(),
    )
    repository._upsert("source_spans", span)
    evidence = (
        item.facts[0]
        .evidence_refs[0]
        .model_copy(
            update={
                "record_type": "source_span",
                "record_id": span.id,
                "version": 1,
                "content_hash": source_span_hash(span),
            }
        )
    )
    item.facts = [item.facts[0].model_copy(update={"evidence_refs": [evidence]})]
    repository.save_user_memory_item(item)
    assert _graph(service, owner, "user_memory_item", item.id).edges[0].relation_type == "cites"
    assert _graph(service, owner, "document", document.id).edges[0].from_key == f"user_memory_item:{item.id}"
    repository._upsert("source_spans", span.model_copy(update={"quote": "Alice"}))
    assert _graph(service, owner, "user_memory_item", item.id).edges == []
    assert _graph(service, owner, "document", document.id).edges == []


@pytest.mark.parametrize("source_kind", ["document_import", "promoted"])
def test_literal_import_is_rechecked_but_a_legacy_version_link_does_not_invent_hash_provenance(
    relation_project, source_kind
):
    repository, owner, _, document, memory, service = relation_project
    memory.source_kind, memory.summary = source_kind, document.text
    memory.sources = [document.source.model_copy(update={"reference": f"document://{document.id}#v1/chunk_0"})]
    repository.save_user_memory_item(memory)
    graph = _graph(service, owner, "user_memory_item", memory.id)
    assert bool(graph.edges) == (source_kind == "document_import")
    document.text = "Changed raw body"
    repository.save_document(document)
    assert _graph(service, owner, "user_memory_item", memory.id).edges == []


@pytest.mark.parametrize("authority", ["user", "project"])
def test_authority_payloads_are_bounded_before_decode(relation_project, authority):
    repository, owner, _, _, memory, service = relation_project
    if authority == "user":
        repository.save_user(owner.model_copy(update={"name": "x" * 65536}))
    else:
        repository.save_project(repository.get_project("project").model_copy(update={"goal": "x" * 262144}))
    with pytest.raises(MemoryRelationError):
        _graph(service, owner, "user_memory_item", memory.id)


def test_query_contract_rejects_unbounded_or_unknown_client_options():
    clear_store()
    client = authenticated_client()
    for invalid in (
        {"max_hops": 3},
        {"max_nodes": 41},
        {"max_edges": 81},
        {"max_chars": 12001},
        {"include_private": True},
    ):
        response = _query(client, "task", "missing", **invalid)
        assert response.status_code == 422


def test_global_memory_cannot_claim_a_project_document_as_native_source(relation_project):
    repository, owner, _, document, memory, service = relation_project
    memory.project_id = None
    memory.source_kind, memory.summary = "document_import", document.text
    memory.sources = [
        document.source.model_copy(update={"project_id": None, "reference": f"document://{document.id}#v1/chunk_0"})
    ]
    repository.save_user_memory_item(memory)
    assert _graph(service, owner, "user_memory_item", memory.id).edges == []


def test_unproven_legacy_document_links_do_not_hide_older_frozen_fact_citations(relation_project):
    repository, owner, _, document, memory, service = relation_project
    item = MemoryFactsService(repository).remember(
        FactRememberV1(
            command_id="older-fact",
            project_id="project",
            title="Rollout owner",
            summary="Bob",
            source_document_id=document.id,
            source_version=document.version,
            source_hash=document_evidence_hash(document),
            facts=[
                FactAssertionV1(
                    subject_type="project",
                    subject_id="project",
                    predicate="owner",
                    value="Bob",
                    time_precision="unknown",
                )
            ],
        ),
        owner,
    )
    for index in range(150):
        repository.add_user_memory_item(
            memory.model_copy(
                update={
                    "id": f"unproven-{index}",
                    "sources": [
                        document.source.model_copy(update={"reference": f"document://{document.id}#v1/chunk_0"})
                    ],
                }
            )
        )
    graph = _graph(service, owner, "document", document.id)
    assert any(node.record_id == item.id for node in graph.nodes)
    assert graph.truncated is False


def test_replay_rejects_a_stored_relation_whose_frozen_fields_changed(relation_project):
    repository, owner, _, _, _, service = relation_project
    request = _relation_request(relation_project)
    created = service.create(request, owner)
    repository.add_memory_relation(created.model_copy(update={"relation_type": "contradicts"}))
    with pytest.raises(MemoryRelationError, match="relation_command_conflict"):
        service.create(request, owner)


def test_legacy_identifiers_outside_the_graph_contract_are_skipped_in_backlinks(relation_project):
    repository, owner, _, document, memory, service = relation_project
    legacy = memory.model_copy(
        update={
            "id": "x" * 121,
            "source_kind": "document_import",
            "summary": document.text,
            "sources": [document.source.model_copy(update={"reference": f"document://{document.id}#v1/chunk_0"})],
        }
    )
    repository.add_user_memory_item(legacy)
    assert _graph(service, owner, "document", document.id).edges == []
