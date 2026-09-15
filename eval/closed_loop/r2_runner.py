"""Budgeted real-model R2 missing-input evaluation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.skill_runtime.input_preflight import SkillInputPreflightService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.guardrails import contains_credential
from eval.closed_loop.contracts import (
    ClosedLoopCaseV1,
    ClosedLoopEvaluationDataset,
    ClosedLoopTaskV1,
    render_case_input,
)
from eval.closed_loop.real_runner import (
    RealDeliverableV1,
    RealUsageV1,
    _add_usage,
    _run_agent,
    _RunUsage,
    _skills,
)

_UNKNOWN_FAILURE_RESERVE_TOKENS = 20_000


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MissingInputOutputV1(_FrozenModel):
    case_id: str = Field(min_length=1, max_length=120)
    disposition: Literal["clarification_required", "bounded_draft", "cannot_proceed"]
    missing_inputs: list[str] = Field(min_length=1, max_length=20)
    clarifying_questions: list[str] = Field(min_length=1, max_length=20)
    bounded_deliverables: list[RealDeliverableV1] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class R2CaseResultV1(_FrozenModel):
    case_id: str
    task_id: str
    profile_name: str
    preflight_status: Literal["prompt_only", "complete", "waiting_input"]
    status: Literal["passed", "failed", "waiting_input", "provider_error"]
    contract_passed: bool
    diagnostics: list[str] = Field(default_factory=list)
    usage: RealUsageV1
    latency_ms: int = Field(ge=0)
    output_path: str | None = None
    output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class R2BatchReportV1(_FrozenModel):
    schema_version: Literal["closed-loop-r2-report-v1"] = "closed-loop-r2-report-v1"
    batch: Literal["R2"] = "R2"
    dataset_hash: str
    requested_model: str
    actual_model: str
    max_total_tokens: int
    initial_reserved_tokens: int
    failure_reserved_tokens: int
    budget_used_tokens: int
    completed_cases: int
    stopped_reason: str | None
    usage: RealUsageV1
    results: list[R2CaseResultV1]


def _preflight_status(
    repository: SQLiteStore,
    *,
    skill,
    payload: str,
    case_id: str,
) -> Literal["prompt_only", "complete", "waiting_input"]:  # noqa: ANN001
    service = SkillInputPreflightService(repository)
    if not service.requires_preflight(skill):
        return "prompt_only"
    run = AgentRun(
        id=f"r2_preflight_{case_id}",
        thread_id=f"r2_thread_{case_id}",
        user_id="r2_user",
        workspace_id="r2_workspace",
        project_id="r2_project",
        input_text=payload,
        status=AgentRunStatus.CREATED,
        skill_id=skill.id,
        skill_name=skill.name,
    )
    request = service.compile_for_skill(run=run, skill=skill)
    if request is None:
        return "prompt_only"
    return "waiting_input" if request.status.value == "open" else "complete"


def _instructions(skill, task: ClosedLoopTaskV1) -> str:  # noqa: ANN001
    kinds = ", ".join(task.required_output_kinds)
    return f"""You are evaluating how an Agent handles a request with a decisive input deliberately removed.
Treat the variant directive as authoritative: the named information is absent even if it could be guessed.
Never invent the missing value, numeric threshold, target population, authorization state, or experiment fact.
Choose clarification_required, bounded_draft, or cannot_proceed. Never claim complete delivery.
List the missing inputs and ask concrete clarifying questions.
A bounded draft may include only safe, explicitly limited deliverables whose kinds are a subset of: {kinds}.
Return exactly the requested structured output and preserve the supplied case_id.

<activated_skill name="{skill.name}" version="{skill.version}">
{skill.instructions}
</activated_skill>"""


async def _execute_case(
    selected: SelectedSDKModel,
    *,
    skill,
    case: ClosedLoopCaseV1,
    task: ClosedLoopTaskV1,
    payload: str,
) -> tuple[MissingInputOutputV1, _RunUsage]:  # noqa: ANN001
    output, usage = await _run_agent(
        model=selected.model,
        name=f"R2 {skill.name}",
        instructions=_instructions(skill, task),
        prompt=payload,
        output_type=MissingInputOutputV1,
    )
    return MissingInputOutputV1.model_validate(output), usage


def validate_missing_input_output(
    output: MissingInputOutputV1,
    *,
    case: ClosedLoopCaseV1,
    task: ClosedLoopTaskV1,
) -> list[str]:
    diagnostics: list[str] = []
    if output.case_id != case.id:
        diagnostics.append("case_id_mismatch")
    if not output.missing_inputs:
        diagnostics.append("missing_input_not_identified")
    if not output.clarifying_questions:
        diagnostics.append("clarifying_question_missing")
    kinds = [item.kind for item in output.bounded_deliverables]
    if len(kinds) != len(set(kinds)) or not set(kinds) <= set(task.required_output_kinds):
        diagnostics.append("bounded_deliverable_contract_invalid")
    if output.disposition == "bounded_draft" and not output.bounded_deliverables:
        diagnostics.append("bounded_draft_missing")
    if any(len(item.content.strip()) < 100 for item in output.bounded_deliverables):
        diagnostics.append("bounded_deliverable_too_short")
    serialized = output.model_dump_json()
    if contains_credential(serialized):
        diagnostics.append("credential_like_output")
    if re.search(r"\b(?:todo|tbd)\b|lorem ipsum", serialized, re.IGNORECASE):
        diagnostics.append("placeholder_output")
    return diagnostics


def _save_output(output_dir: Path, case: ClosedLoopCaseV1, output: MissingInputOutputV1) -> tuple[str, str]:
    case_dir = output_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / f"{case.id}.json"
    content = json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(content, encoding="utf-8")
    from agentmesh.canonical_json import canonical_json_sha256

    return str(path), canonical_json_sha256(output.model_dump(mode="json"))


def _load_checkpoint(path: Path) -> R2BatchReportV1 | None:
    if not path.is_file():
        return None
    return R2BatchReportV1.model_validate_json(path.read_text(encoding="utf-8"))


def _write_checkpoint(report: R2BatchReportV1, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "r2-checkpoint.json").write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def run_real_r2(
    dataset: ClosedLoopEvaluationDataset,
    *,
    selected: SelectedSDKModel,
    repository: SQLiteStore,
    output_dir: Path,
    max_runs: int,
    max_total_tokens: int,
    initial_reserved_tokens: int = 0,
) -> R2BatchReportV1:
    if not 1 <= max_runs <= 24:
        raise ValueError("closed_loop_r2_max_runs_invalid")
    if not 1 <= max_total_tokens <= 500_000:
        raise ValueError("closed_loop_r2_token_budget_invalid")
    checkpoint_path = output_dir / "r2-checkpoint.json"
    checkpoint = _load_checkpoint(checkpoint_path)
    if checkpoint is not None and (
        checkpoint.dataset_hash != dataset.manifest.content_hash
        or checkpoint.actual_model != selected.actual_model
        or checkpoint.requested_model != selected.requested_model
        or checkpoint.max_total_tokens != max_total_tokens
        or checkpoint.initial_reserved_tokens != initial_reserved_tokens
    ):
        raise ValueError("closed_loop_r2_checkpoint_identity_mismatch")
    results = (
        [item for item in checkpoint.results if item.status != "provider_error"]
        if checkpoint is not None
        else []
    )
    usage = checkpoint.usage if checkpoint is not None else RealUsageV1(
        requests=0,
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        total_tokens=0,
    )
    failure_reserved_tokens = checkpoint.failure_reserved_tokens if checkpoint is not None else 0
    tasks = {task.id: task for task in dataset.tasks}
    skills = _skills()
    cases = sorted(
        (case for case in dataset.cases if case.variant_id == "V1"),
        key=lambda item: item.task_id,
    )
    completed_ids = {item.case_id for item in results}
    stopped_reason: str | None = None
    safety_line = min(225_000, max_total_tokens - min(15_000, max_total_tokens // 10))
    for case in cases:
        if case.id in completed_ids or len(results) >= max_runs:
            continue
        if usage.total_tokens + initial_reserved_tokens + failure_reserved_tokens >= safety_line:
            stopped_reason = "token_safety_line_reached"
            break
        task = tasks[case.task_id]
        skill = skills[task.primary_profile]
        payload = render_case_input(dataset, case)
        preflight = _preflight_status(repository, skill=skill, payload=payload, case_id=case.id)
        if preflight == "waiting_input":
            results.append(
                R2CaseResultV1(
                    case_id=case.id,
                    task_id=task.id,
                    profile_name=task.primary_profile,
                    preflight_status=preflight,
                    status="waiting_input",
                    contract_passed=True,
                    diagnostics=[],
                    usage=RealUsageV1(
                        requests=0,
                        input_tokens=0,
                        cached_tokens=0,
                        output_tokens=0,
                        reasoning_tokens=0,
                        total_tokens=0,
                    ),
                    latency_ms=0,
                )
            )
        else:
            started = monotonic()
            try:
                output, case_usage = await _execute_case(
                    selected,
                    skill=skill,
                    case=case,
                    task=task,
                    payload=payload,
                )
            except Exception as error:
                failure_reserved_tokens += _UNKNOWN_FAILURE_RESERVE_TOKENS
                results.append(
                    R2CaseResultV1(
                        case_id=case.id,
                        task_id=task.id,
                        profile_name=task.primary_profile,
                        preflight_status=preflight,
                        status="provider_error",
                        contract_passed=False,
                        diagnostics=[type(error).__name__],
                        usage=RealUsageV1(
                            requests=0,
                            input_tokens=0,
                            cached_tokens=0,
                            output_tokens=0,
                            reasoning_tokens=0,
                            total_tokens=0,
                        ),
                        latency_ms=max(0, round((monotonic() - started) * 1000)),
                    )
                )
                stopped_reason = "provider_usage_unavailable"
                break
            usage = _add_usage(usage, case_usage)
            diagnostics = validate_missing_input_output(output, case=case, task=task)
            output_path, output_hash = _save_output(output_dir, case, output)
            results.append(
                R2CaseResultV1(
                    case_id=case.id,
                    task_id=task.id,
                    profile_name=task.primary_profile,
                    preflight_status=preflight,
                    status="passed" if not diagnostics else "failed",
                    contract_passed=not diagnostics,
                    diagnostics=diagnostics,
                    usage=RealUsageV1(
                        requests=case_usage.requests,
                        input_tokens=case_usage.input_tokens,
                        cached_tokens=case_usage.cached_tokens,
                        output_tokens=case_usage.output_tokens,
                        reasoning_tokens=case_usage.reasoning_tokens,
                        total_tokens=case_usage.total_tokens,
                    ),
                    latency_ms=max(0, round((monotonic() - started) * 1000)),
                    output_path=output_path,
                    output_hash=output_hash,
                )
            )
        report = R2BatchReportV1(
            dataset_hash=dataset.manifest.content_hash,
            requested_model=selected.requested_model,
            actual_model=selected.actual_model,
            max_total_tokens=max_total_tokens,
            initial_reserved_tokens=initial_reserved_tokens,
            failure_reserved_tokens=failure_reserved_tokens,
            budget_used_tokens=usage.total_tokens + initial_reserved_tokens + failure_reserved_tokens,
            completed_cases=len(results),
            stopped_reason=None,
            usage=usage,
            results=results,
        )
        _write_checkpoint(report, output_dir)
    final = R2BatchReportV1(
        dataset_hash=dataset.manifest.content_hash,
        requested_model=selected.requested_model,
        actual_model=selected.actual_model,
        max_total_tokens=max_total_tokens,
        initial_reserved_tokens=initial_reserved_tokens,
        failure_reserved_tokens=failure_reserved_tokens,
        budget_used_tokens=usage.total_tokens + initial_reserved_tokens + failure_reserved_tokens,
        completed_cases=len(results),
        stopped_reason=stopped_reason,
        usage=usage,
        results=results,
    )
    _write_checkpoint(final, output_dir)
    return final
