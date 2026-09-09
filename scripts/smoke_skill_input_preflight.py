#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.input_adapters import RunInputAdapterError, parse_run_input
from agentmesh.models import (
    AgentRunStatus,
    ChatThread,
    RunInputArtifactStatus,
    RunInputArtifactV1,
    SkillInputRequestStatus,
    SkillInputSubmitRequest,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def _wiki_fixture(root: Path) -> None:
    files = (
        root / "jd-design-system-md-v16" / "horizontal" / "user-research" / "canonical.md",
        root
        / "jd-design-system-md-v16"
        / "product-architecture"
        / "comprehensive-business"
        / "content-ecosystem"
        / "canonical.md",
        root
        / "jd-design-system-md-v16"
        / "product-architecture"
        / "plus-and-new-channel"
        / "_knowledge"
        / "experiments"
        / "INDEX.json",
    )
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "canonical", encoding="utf-8")


async def _run_smoke(root: Path) -> dict[str, object]:
    wiki_root = root / "wiki"
    _wiki_fixture(wiki_root)
    os.environ["AGENTMESH_WIKI_ROOT"] = str(wiki_root)
    repository = SQLiteStore(root / "skill-input-smoke.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_skill_input_smoke",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Skill Input Smoke",
        )
    )
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("build-experience-metrics", USER.personal_agent_id)
    if skill is None:
        raise RuntimeError("smoke_skill_unavailable")
    model = ScriptedModel([[assistant_message("已根据冻结输入生成体验度量方案。")]])
    runtime = AgentRuntimeService(
        repository=repository,
        model=model,
        enabled=True,
        skill_catalog=catalog,
    )

    waiting = await runtime.start(
        content="$build-experience-metrics",
        user=USER,
        thread_id=thread.id,
        history=[],
        skill=skill,
        client_turn_id="turn_skill_input_smoke",
    )
    request = repository.get_skill_input_request_for_run(waiting.id)
    if (
        waiting.status is not AgentRunStatus.WAITING_INPUT
        or request is None
        or request.status is not SkillInputRequestStatus.OPEN
        or model.first_call is not None
    ):
        raise RuntimeError("smoke_waiting_gate_failed")
    if repository.list_skill_node_results(waiting.plan_id or ""):
        raise RuntimeError("smoke_node_started_before_input")

    try:
        parse_run_input(
            file_name="invalid.csv",
            declared_media_type="text/csv",
            content=b"date,date\n1,2\n",
            accepted_media_types=["text/csv"],
        )
    except RunInputAdapterError as error:
        if error.code != "input_csv_duplicate_header":
            raise
    else:
        raise RuntimeError("smoke_invalid_csv_accepted")

    draft_submission = SkillInputSubmitRequest(
        client_turn_id="turn_skill_input_smoke_draft",
        expected_request_version=request.version,
        text_values={"direct.product_goal": "提升新用户首周激活率，同时守住任务成功率"},
        advance=False,
    )
    draft, _ = runtime.input_preflight.apply_submission(request, draft_submission)
    persisted_draft, draft_run, replayed = repository.update_skill_input_request(
        draft,
        expected_version=request.version,
    )
    if replayed or draft_run.status is not AgentRunStatus.WAITING_INPUT:
        raise RuntimeError("smoke_draft_transition_failed")

    restarted_runtime = AgentRuntimeService(
        repository=repository,
        model=model,
        enabled=True,
        skill_catalog=catalog,
    )
    recovered = repository.get_skill_input_request_for_run(waiting.id)
    if recovered is None or recovered.version != persisted_draft.version:
        raise RuntimeError("smoke_restart_recovery_failed")
    goal = next(field for field in recovered.fields if field.id == "direct.product_goal")
    if goal.text_value != "提升新用户首周激活率，同时守住任务成功率":
        raise RuntimeError("smoke_draft_value_lost")

    second_run_blocked = False
    try:
        await restarted_runtime.start(
            content="another active run",
            user=USER,
            thread_id=thread.id,
            history=[],
            skill=skill,
            client_turn_id="turn_skill_input_smoke_conflict",
        )
    except RuntimeError as error:
        second_run_blocked = "already active" in str(error)
    if not second_run_blocked:
        raise RuntimeError("smoke_second_run_not_blocked")

    csv_content = b"date,value\n2026-09-01,12\n2026-09-02,14\n"
    parsed = parse_run_input(
        file_name="baseline.csv",
        declared_media_type="text/csv",
        content=csv_content,
        accepted_media_types=["text/csv"],
    )
    artifact = repository.save_run_input_artifact(
        RunInputArtifactV1(
            id="input_artifact_skill_input_smoke",
            run_id=waiting.id,
            workspace_id=waiting.workspace_id,
            project_id=waiting.project_id,
            user_id=waiting.user_id,
            field_id="direct.baseline_metrics",
            file_name="baseline.csv",
            media_type=parsed.media_type,
            byte_size=len(csv_content),
            content_hash=hashlib.sha256(csv_content).hexdigest(),
            adapter_id=parsed.adapter_id,
            adapter_version=parsed.adapter_version,
            status=RunInputArtifactStatus.READY,
            normalized_text=parsed.normalized_text,
            structured_payload=parsed.structured_payload,
        ),
        csv_content,
        expected_request_version=recovered.version,
    )
    if repository.user_memory_items:
        raise RuntimeError("smoke_input_created_memory")

    submit = SkillInputSubmitRequest(
        client_turn_id="turn_skill_input_smoke_submit",
        expected_request_version=recovered.version,
        text_values={"direct.product_goal": goal.text_value or ""},
        artifact_ids={"direct.baseline_metrics": [artifact.id]},
    )
    completed_request, _ = restarted_runtime.input_preflight.apply_submission(recovered, submit)
    restarted_runtime.validate_input_resume(
        run=draft_run,
        user=USER,
        request=completed_request,
    )
    dispatch = restarted_runtime.new_dispatch_receipt(waiting.id, "standard_direct")
    frozen, running, replayed = repository.update_skill_input_request(
        completed_request,
        expected_version=recovered.version,
        dispatch=dispatch,
    )
    if replayed or frozen.status is not SkillInputRequestStatus.COMPLETE:
        raise RuntimeError("smoke_input_freeze_failed")
    await restarted_runtime.resume_after_input(
        running.id,
        user=USER,
        dispatch_receipt=dispatch,
    )
    await restarted_runtime._tasks[running.id]
    finished = repository.get_agent_run(running.id)
    if finished is None or finished.status is not AgentRunStatus.COMPLETED:
        raise RuntimeError("smoke_execution_failed")
    if model.first_call is None:
        raise RuntimeError("smoke_model_not_called")
    model_input = json.loads(model.first_call.input[-1]["content"])
    baseline = model_input["user_inputs"]["baseline_metrics"][0]
    if baseline["artifact_id"] != artifact.id or baseline["structured_payload"]["row_count"] != 2:
        raise RuntimeError("smoke_binding_not_delivered")
    if any(item.source_kind == "run_input" for item in repository.user_memory_items):
        raise RuntimeError("smoke_input_memory_leak")

    replay, _ = restarted_runtime.input_preflight.apply_submission(frozen, submit)
    if replay.version != frozen.version:
        raise RuntimeError("smoke_idempotent_replay_failed")
    result = {
        "run_id": finished.id,
        "status": finished.status.value,
        "input_request_version": frozen.version,
        "binding_count": len(frozen.frozen_bindings),
        "artifact_hash": artifact.content_hash,
        "model_called": model.first_call is not None,
        "second_run_blocked": second_run_blocked,
        "input_memory_items": 0,
    }
    repository.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fresh-DB Skill Input Preflight vertical smoke")
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()
    if args.workdir is not None:
        args.workdir.mkdir(parents=True, exist_ok=True)
        result = asyncio.run(_run_smoke(args.workdir))
    else:
        with tempfile.TemporaryDirectory(prefix="agentmesh-skill-input-smoke-") as directory:
            result = asyncio.run(_run_smoke(Path(directory)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
