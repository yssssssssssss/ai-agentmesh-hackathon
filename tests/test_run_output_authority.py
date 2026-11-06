from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from agents.testing import ScriptedModel, assistant_message
from fastapi.testclient import TestClient

import agentmesh.routes.agent_runs as run_routes
from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.app import app
from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatMessage,
    ChatThread,
    Intent,
    SDKSessionRecord,
    SkillDefinition,
    SkillIntent,
    SkillMemoryWritePolicy,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillResultSource,
    SkillSynthesisResult,
    Source,
    Task,
    new_id,
    now_utc,
    run_output_memory_id,
)
from agentmesh.routes.deps import current_user
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import ResearchStoreConflict, SQLiteStore


@pytest.fixture
def output(tmp_path):
    repository = SQLiteStore(tmp_path / "output-authority.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            user_id=USER.id, workspace_id=USER.workspace_id, project_id=USER.default_project_id, title="Current output"
        )
    )
    skill = repository.save_skill_definition(
        SkillDefinition(
            id="output_skill",
            name="output-skill",
            title="Private skill output",
            description="Return private output",
            instructions="Return output",
            source_path="/virtual/output/SKILL.md",
            source_scope="builtin",
            content_hash="a" * 64,
            memory_write_policy="private_short_term",
        ),
        defer_vector=True,
    )
    run = repository.save_agent_run(
        AgentRun(
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            skill_id=skill.id,
            input_text="$output-skill",
            status="completed",
            writer_generation_epoch=1,
            output_text="Current private result",
            project_chat=True,
        )
    )
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    selected = SelectedSDKModel(model=model, requested_model="scripted", actual_model="scripted")
    yield repository, runtime, run, skill, selected
    repository.close()


def test_owner_revoked_at_output_write_cannot_create_chat_memory_or_receipt(output, monkeypatch):
    repository, runtime, run, _skill, selected = output
    original = repository.project_terminal_run_output

    def revoke_then_write(**kwargs):
        repository.save_user(USER.model_copy(update={"status": "disabled"}))
        return original(**kwargs)

    monkeypatch.setattr(repository, "project_terminal_run_output", revoke_then_write)
    with pytest.raises(ResearchStoreConflict, match="run_output_not_authorized"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id) is None
    assert repository.get_agent_run(run.id).output_text == "Current private result"
    assert not any(event.event_type == "run_output_projected" for event in repository.list_agent_run_events(run.id))


@pytest.mark.parametrize(
    "change", ["project_archived", "membership", "workspace", "thread_archived", "thread_owner", "thread_project"]
)
def test_current_project_and_thread_authority_controls_output_write(output, change):
    repository, runtime, run, _skill, selected = output
    if change in {"project_archived", "membership"}:
        project = repository.get_project(run.project_id)
        update = {"status": "archived"} if change == "project_archived" else {"member_ids": ["other_member"]}
        repository.save_project(project.model_copy(update=update))
    elif change == "workspace":
        repository.save_user(USER.model_copy(update={"workspace_id": "other_workspace"}))
    else:
        update = {
            "thread_archived": {"status": "archived"},
            "thread_owner": {"user_id": "other_owner"},
            "thread_project": {"project_id": "other_project"},
        }[change]
        repository.save_chat_thread(repository.get_chat_thread(run.thread_id).model_copy(update=update))

    with pytest.raises(ResearchStoreConflict, match="run_output_not_authorized"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_run_output_projection(run.id) is None
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None


@pytest.mark.parametrize("session_kind", ["unowned_body", "new_generation"])
def test_unproven_session_body_or_replaced_session_writer_blocks_output(output, session_kind):
    repository, runtime, run, _skill, selected = output
    if session_kind == "unowned_body":
        session = SDKSessionRecord(id=run.thread_id, items=[{"role": "assistant", "content": "Unknown origin"}])
        code = "run_output_session_unverified"
    else:
        session = SDKSessionRecord(
            id=run.thread_id,
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            writer_run_id=run.id,
            writer_generation_epoch=2,
            version=8,
        )
        code = "run_output_session_writer_changed"
    repository.save_sdk_session(session)

    with pytest.raises(ResearchStoreConflict, match=code):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.get_sdk_session(run.thread_id) == session
    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_run_output_projection(run.id) is None


@pytest.mark.parametrize("session_kind", ["other_writer", "withdrawn"])
def test_valid_chat_output_keeps_other_writer_or_withdrawn_session_unchanged(output, session_kind):
    repository, runtime, run, _skill, selected = output
    session = SDKSessionRecord(
        id=run.thread_id,
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        writer_run_id="next_run" if session_kind == "other_writer" else run.id,
        writer_generation_epoch=1,
        source_status="withdrawn" if session_kind == "withdrawn" else "active",
        version=5,
    )
    repository.save_sdk_session(session)

    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.get_sdk_session(run.thread_id) == session
    assert [message.content for message in repository.list_thread_messages(run.thread_id)] == ["Current private result"]
    assert repository.get_run_output_projection(run.id).disposition == "message"


def test_shared_task_output_does_not_acquire_requesters_private_session(output):
    repository, runtime, run, _skill, selected = output
    thread = repository.get_chat_thread(run.thread_id)
    repository.save_chat_thread(ChatThread(**{**thread.model_dump(), "kind": "task", "user_id": "task_requester"}))
    task = repository.save_task(Task(thread_id=thread.id, title="Shared task", intent=Intent.GENERAL_CHAT))
    run = repository.save_agent_run(run.model_copy(update={"id": new_id("run"), "task_id": task.id}))
    session = repository.save_sdk_session(
        SDKSessionRecord(
            id=run.thread_id,
            user_id="task_requester",
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            writer_run_id="requester_run",
            version=4,
        )
    )

    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.get_sdk_session(run.thread_id) == session
    assert repository.get_run_output_projection(run.id).disposition == "message"
    memory = repository.get_user_memory_item(run_output_memory_id(run.id))
    assert memory.user_id == run.user_id and memory.scope.value == "private"
    assert repository.get_task(task.id) == task


def test_duplicate_projection_after_reopen_keeps_one_owned_message_and_memory(output):
    repository, runtime, run, _skill, selected = output
    runtime.project_orchestration_output(run, run.output_text, selected=selected)
    receipt = repository.get_run_output_projection(run.id)
    repository.close()
    reopened = SQLiteStore(repository.db_path)
    try:
        AgentRuntimeService(reopened, model=selected.model, enabled=True).project_orchestration_output(
            run, run.output_text, selected=selected
        )
        assert reopened.get_run_output_projection(run.id) == receipt
        assert len(reopened.list_thread_messages(run.thread_id)) == 1
        session = reopened.get_sdk_session(run.thread_id)
        assert (session.user_id, session.workspace_id, session.project_id) == (
            run.user_id,
            run.workspace_id,
            run.project_id,
        )
        assert session.writer_run_id == run.id and session.writer_generation_epoch == 1
        assert session.version == 1
        assert session.synced_chat_message_ids == [receipt.assistant_message_id]
    finally:
        reopened.close()


def test_revoked_owner_cannot_replay_a_previously_projected_body(output):
    repository, runtime, run, _skill, selected = output
    runtime.project_orchestration_output(run, run.output_text, selected=selected)
    receipt = repository.get_run_output_projection(run.id)
    session = repository.get_sdk_session(run.thread_id)
    repository.save_user(USER.model_copy(update={"status": "disabled"}))

    with pytest.raises(ResearchStoreConflict, match="run_output_not_authorized"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)
    assert repository.save_terminal_run_memory(run_id=run.id, user_id=run.user_id, expected_run=run) is None
    assert repository.get_run_output_projection(run.id) == receipt
    assert repository.get_sdk_session(run.thread_id) == session
    assert len(repository.list_thread_messages(run.thread_id)) == 1


def test_sealed_output_can_be_projected_after_execution_deadline(output):
    repository, runtime, run, _skill, selected = output
    run = repository.save_agent_run(
        run.model_copy(
            update={
                "deadline_at": now_utc() - timedelta(seconds=1),
                "absolute_expires_at": now_utc() - timedelta(seconds=1),
            }
        )
    )

    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.get_run_output_projection(run.id).disposition == "message"
    assert len(repository.list_thread_messages(run.thread_id)) == 1


def test_projection_event_failure_rolls_back_message_memory_session_and_thread(output):
    repository, runtime, run, _skill, selected = output
    thread = repository.get_chat_thread(run.thread_id)
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER fail_output_event BEFORE INSERT ON agent_run_events
            WHEN json_extract(NEW.payload, '$.event_type') = 'run_output_projected'
            BEGIN SELECT RAISE(ABORT, 'controlled_output_failure'); END""")

    with pytest.raises(sqlite3.IntegrityError, match="controlled_output_failure"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id) is None
    assert repository.get_sdk_session(run.thread_id) is None
    assert repository.get_chat_thread(run.thread_id) == thread
    assert repository.get_agent_run(run.id) == run
    with repository._connect() as connection:
        connection.execute("DROP TRIGGER fail_output_event")
    runtime.project_orchestration_output(run, run.output_text, selected=selected)
    assert len(repository.list_thread_messages(run.thread_id)) == 1
    assert repository.get_run_output_projection(run.id).memory_disposition == "projected"


def test_concurrent_duplicate_output_projection_has_one_receipt_and_event(output):
    repository, runtime, run, _skill, selected = output
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(runtime.project_orchestration_output, run, run.output_text, selected=selected) for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=10)

    assert len(repository.list_thread_messages(run.thread_id)) == 1
    assert repository.get_sdk_session(run.thread_id).version == 1
    assert (
        len([event for event in repository.list_agent_run_events(run.id) if event.event_type == "run_output_projected"])
        == 1
    )


def test_old_writer_cannot_project_same_text_for_new_generation(output):
    repository, runtime, run, _skill, selected = output
    repository.save_agent_run(run.model_copy(update={"writer_generation_epoch": 2}))

    with pytest.raises(ResearchStoreConflict, match="run_output_writer_changed"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id) is None
    assert repository.get_agent_run(run.id).writer_generation_epoch == 2


def test_memory_policy_revoked_before_commit_keeps_chat_without_automatic_memory(output, monkeypatch):
    repository, runtime, run, skill, selected = output
    original = repository.project_terminal_run_output

    def revoke_then_write(**kwargs):
        repository.save_skill_definition(
            skill.model_copy(update={"memory_write_policy": SkillMemoryWritePolicy.NONE}), defer_vector=True
        )
        return original(**kwargs)

    monkeypatch.setattr(repository, "project_terminal_run_output", revoke_then_write)
    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert [message.content for message in repository.list_thread_messages(run.thread_id)] == ["Current private result"]
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id).memory_disposition == "policy_skipped"


def test_output_cannot_modify_another_owners_session(output):
    repository, runtime, run, _skill, selected = output
    session = repository.save_sdk_session(
        SDKSessionRecord(
            id=run.thread_id,
            user_id="other_owner",
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            writer_run_id="other_run",
            version=7,
        )
    )

    with pytest.raises(ResearchStoreConflict, match="run_output_session_not_authorized"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id) is None
    assert repository.get_sdk_session(run.thread_id) == session


def test_manual_run_memory_save_rechecks_current_owner_authority(output):
    repository, _runtime, run, _skill, _selected = output
    repository.save_user(USER.model_copy(update={"status": "disabled"}))

    assert (
        repository.save_terminal_run_memory(run_id=run.id, user_id=run.user_id, expected_run=run, title="Saved result")
        is None
    )
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None


def test_manual_memory_http_save_rejects_output_changed_after_validation(output, monkeypatch):
    repository, _runtime, run, _skill, _selected = output
    original = repository.save_terminal_run_memory
    monkeypatch.setattr(run_routes, "store", repository)

    def change_then_save(**kwargs):
        repository.save_agent_run(run.model_copy(update={"output_text": "Changed after validation"}))
        return original(**kwargs)

    monkeypatch.setattr(repository, "save_terminal_run_memory", change_then_save)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[current_user] = lambda: USER
    try:
        response = TestClient(app).post(f"/api/agent/runs/{run.id}/memory", json={"title": "Original result"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "run_output_memory_unavailable"
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None


def test_pending_chat_projection_preserves_already_manually_saved_memory(output):
    repository, runtime, run, _skill, selected = output
    saved = repository.save_terminal_run_memory(
        run_id=run.id, user_id=run.user_id, expected_run=run, title="My saved result"
    )

    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert len(repository.list_thread_messages(run.thread_id)) == 1
    assert repository.get_user_memory_item(saved.id) == saved
    receipt = repository.get_run_output_projection(run.id)
    assert receipt.memory_item_id == saved.id
    assert receipt.memory_disposition == "projected"


def test_forgotten_run_memory_is_not_restored_by_manual_save_or_pending_projection(output):
    repository, runtime, run, _skill, selected = output
    saved = repository.save_terminal_run_memory(run_id=run.id, user_id=run.user_id, expected_run=run)
    MemoryForgettingService(repository).forget(
        saved.id, MemoryForgetRequestV1(command_id="forget-run-output", expected_version=1), USER
    )
    forgotten = repository.get_user_memory_item(saved.id)

    assert repository.save_terminal_run_memory(run_id=run.id, user_id=run.user_id, expected_run=run) is None
    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.get_user_memory_item(saved.id) == forgotten
    assert forgotten.summary == "" and forgotten.status != "active"
    receipt = repository.get_run_output_projection(run.id)
    assert receipt.memory_item_id is None and receipt.memory_disposition == "policy_skipped"
    assert len(repository.list_thread_messages(run.thread_id)) == 1


@pytest.mark.parametrize("target", ["message", "memory"])
def test_projection_replay_rejects_relocated_stored_body(output, target):
    repository, runtime, run, _skill, selected = output
    runtime.project_orchestration_output(run, run.output_text, selected=selected)
    if target == "message":
        message = repository.list_thread_messages(run.thread_id)[0]
        repository.add_chat_message(message.model_copy(update={"thread_id": "foreign_thread"}))
        code = "run_output_projection_message_conflict"
    else:
        memory = repository.get_user_memory_item(run_output_memory_id(run.id))
        repository.save_user_memory_item(memory.model_copy(update={"user_id": "foreign_owner"}))
        code = "run_output_memory_identity_conflict"

    with pytest.raises(ResearchStoreConflict, match=code):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)


@pytest.mark.parametrize("change", ["policy", "disabled"])
def test_standard_plan_memory_uses_current_skill_policy_at_output_commit(output, monkeypatch, change):
    repository, runtime, run, skill, selected = output
    plan_id = new_id("plan")
    run = repository.save_agent_run(run.model_copy(update={"id": new_id("run"), "plan_id": plan_id, "skill_id": None}))
    repository.save_skill_plan(
        SkillPlan(
            id=plan_id,
            run_id=run.id,
            status="completed",
            intent=SkillIntent(goal="Current Standard result"),
            candidate_skill_ids=[skill.id],
            nodes=[
                SkillPlanNode(
                    skill_id=skill.id,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    status="completed",
                    reason="Produce result",
                )
            ],
        )
    )
    original = repository.project_terminal_run_output

    def revoke_then_write(**kwargs):
        update = {"memory_write_policy": SkillMemoryWritePolicy.NONE} if change == "policy" else {"enabled": False}
        repository.save_skill_definition(skill.model_copy(update=update), defer_vector=True)
        return original(**kwargs)

    monkeypatch.setattr(repository, "project_terminal_run_output", revoke_then_write)
    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert len(repository.list_thread_messages(run.thread_id)) == 1
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id).memory_disposition == "policy_skipped"


def test_output_cannot_create_an_orphan_chat_destination(output):
    repository, runtime, run, _skill, selected = output
    run = repository.save_agent_run(run.model_copy(update={"id": new_id("run"), "thread_id": "missing_thread"}))

    with pytest.raises(ResearchStoreConflict, match="run_output_not_authorized"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)

    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_sdk_session(run.thread_id) is None
    assert repository.get_run_output_projection(run.id) is None


def test_execution_cannot_adopt_a_writer_replaced_after_synthesis_seal(output, monkeypatch):
    repository, _runtime, original_run, skill, _selected = output
    monkeypatch.setenv("AGENTMESH_MEMORY_CONTEXT", "off")
    plan_id = new_id("plan")
    run = repository.save_agent_run(
        original_run.model_copy(
            update={
                "id": new_id("run"),
                "plan_id": plan_id,
                "skill_id": None,
                "status": AgentRunStatus.RUNNING,
                "output_text": None,
            }
        )
    )
    node = SkillPlanNode(
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        status="completed",
        reason="Existing result",
        output_contract=["analysis_result"],
        attempt=1,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id=plan_id,
            run_id=run.id,
            status="approved",
            intent=SkillIntent(goal="Current output"),
            candidate_skill_ids=[skill.id],
            nodes=[node],
            output_contract=["analysis_result"],
        )
    )
    source = repository.add_source(
        Source(
            title="Current evidence",
            source_type="web_page",
            reference="https://example.test/current",
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            run_id=run.id,
            skill_id=skill.id,
        )
    )
    result = repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            node_id=node.id,
            skill_id=skill.id,
            summary="Current private result",
            attempt=1,
            sources=[SkillResultSource(**source.model_dump())],
        ),
    )
    synthesis = SkillSynthesisResult(
        summary="Current private result",
        claims=[{"text": "Current private result", "node_result_ids": [result.id], "source_ids": [source.id]}],
    )
    model = ScriptedModel([[assistant_message(synthesis.model_dump_json())]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    original_finish = repository.finish_skill_plan_and_run

    def replace_after_seal(**kwargs):
        transition = original_finish(**kwargs)
        if transition is not None and kwargs["plan"].synthesis is not None:
            repository.save_agent_run(transition[1].model_copy(update={"writer_generation_epoch": 2}))
        return transition

    monkeypatch.setattr(repository, "finish_skill_plan_and_run", replace_after_seal)
    with pytest.raises(ResearchStoreConflict, match="run_output_writer_changed"):
        asyncio.run(runtime._execute_approved_skill_plan(plan=plan, run=run, user=USER))

    current = repository.get_agent_run(run.id)
    assert current.status in {AgentRunStatus.COMPLETED, AgentRunStatus.PARTIAL}
    assert current.writer_generation_epoch == 2
    assert current.output_text
    assert len(model.calls) == 1
    assert repository.get_run_output_projection(run.id) is None
    assert repository.list_thread_messages(run.thread_id) == []


def test_canonical_message_markers_without_session_body_can_bind_current_thread_owner(output):
    repository, runtime, run, _skill, selected = output
    message = repository.add_chat_message(ChatMessage(thread_id=run.thread_id, role="user", content="Original request"))
    repository.save_sdk_session(SDKSessionRecord(id=run.thread_id, synced_chat_message_ids=[message.id]))

    runtime.project_orchestration_output(run, run.output_text, selected=selected)

    session = repository.get_sdk_session(run.thread_id)
    assert session.user_id == run.user_id and session.writer_run_id == run.id
    assert len(session.synced_chat_message_ids) == 2
    assert len(repository.list_thread_messages(run.thread_id)) == 2


def test_direct_execution_projects_the_sealed_chat_without_automatic_general_memory(output, monkeypatch):
    repository, _runtime, run, _skill, _selected = output
    monkeypatch.setenv("AGENTMESH_MEMORY_CONTEXT", "off")
    run = repository.save_agent_run(
        run.model_copy(
            update={
                "id": new_id("run"),
                "status": AgentRunStatus.RUNNING,
                "output_text": None,
                "skill_id": None,
                "input_text": "Private request",
            }
        )
    )
    model = ScriptedModel([[assistant_message("Direct private result")]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    selected = SelectedSDKModel(model=model, requested_model="scripted", actual_model="scripted")

    answer = asyncio.run(
        runtime._execute_run(
            run=run, selected=selected, content=run.input_text, user=USER, history=[], skill=None, project_chat=True
        )
    )

    assert answer.content == "Direct private result"
    assert repository.get_run_output_projection(run.id).disposition == "message"
    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    assert repository.get_run_output_projection(run.id).memory_disposition == "policy_skipped"


@pytest.mark.parametrize("marker_kind", ["missing", "foreign"])
def test_unowned_session_markers_require_current_canonical_thread_messages(output, marker_kind):
    repository, runtime, run, _skill, selected = output
    message_id = "unknown_message"
    if marker_kind == "foreign":
        message_id = repository.add_chat_message(
            ChatMessage(thread_id="foreign_thread", role="user", content="Foreign request")
        ).id
    session = repository.save_sdk_session(SDKSessionRecord(id=run.thread_id, synced_chat_message_ids=[message_id]))

    with pytest.raises(ResearchStoreConflict, match="run_output_session_unverified"):
        runtime.project_orchestration_output(run, run.output_text, selected=selected)
    assert repository.get_sdk_session(run.thread_id) == session
    assert repository.list_thread_messages(run.thread_id) == []
    assert repository.get_run_output_projection(run.id) is None
