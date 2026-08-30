"""Server-owned research generation and rollout decisions.

This module is deliberately free of FastAPI and concrete Store imports. It owns the
single-writer vocabulary used by the creation route and the transaction coordinator;
SQLite remains authoritative for the generation epoch.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.models import AgentRun
from agentmesh.research_orchestration.v3.common import Identifier, StrictFrozenModel

_RESEARCH_PREVIEW_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_GENERIC_RESEARCH_REQUESTS = {
    "竞品分析",
    "帮我做竞品分析",
    "做一个竞品分析",
    "做份竞品分析",
    "分析一下竞品",
    "看看竞品",
}
_EXCLUDED_RESEARCH_INTENTS = ("尼尔森", "启发式", "可用性问题", "严重度", "真人测试")
_KNOWN_COMPETITORS = ("淘宝", "拼多多", "京东", "抖音", "天猫", "Figma", "Miro")
_GENERIC_SCOPE_PARTS = {
    "竞品",
    "竞对",
    "产品",
    "工具",
    "平台",
    "助手",
    "方案",
    "能力",
    "功能",
    "场景",
    "局限",
    "差异",
    "用户体验",
}
_INVALID_SCOPE_ANSWERS = ("随便", "不知道", "不清楚", "你选", "都可以", "无所谓")
RESEARCH_WRITER_CONTROL_KEY = "global"
RESEARCH_WRITER_CONTROL_SEED_HASH = hashlib.sha256(
    b"research-writer-control-v1:research-v2:1"
).hexdigest()


class ResearchWriterGeneration(StrEnum):
    V2 = "research-v2"
    V3 = "research-v3"


class ResearchWriterLifecycle(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    RETIRED = "retired"

    @property
    def accepts_new_runs(self) -> bool:
        return self == ResearchWriterLifecycle.ACTIVE

    @property
    def allows_continuations(self) -> bool:
        return self != ResearchWriterLifecycle.RETIRED


class ResearchWriterControlV1(StrictFrozenModel):
    control_key: Literal["global"] = "global"
    active_generation: ResearchWriterGeneration
    lifecycle_state: ResearchWriterLifecycle
    generation_epoch: Annotated[int, Field(ge=1)]
    decision_receipt_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    updated_at: datetime

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> ResearchWriterControlV1:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("research writer control timestamp must include a timezone")
        return self


class ResearchRolloutDecision(StrictFrozenModel):
    target: Literal["v1", "research-v2", "research-v3", "blocked"]
    mode: Literal["off", "preview", "execute"]
    reason: Literal[
        "not_research_eligible",
        "orchestration_off",
        "active_research_v2",
        "research_writer_draining",
        "research_v2_retired",
        "v3_preview_allowlisted",
        "v3_preview_not_allowlisted",
        "v3_execute_not_authorized",
    ]

    @property
    def research_generation(self) -> ResearchWriterGeneration | None:
        if self.target == ResearchWriterGeneration.V2.value:
            return ResearchWriterGeneration.V2
        if self.target == ResearchWriterGeneration.V3.value:
            return ResearchWriterGeneration.V3
        return None


def parse_research_preview_allowlist(raw: str) -> frozenset[str]:
    """Parse an exact server-owned user allowlist; wildcard rollout is forbidden."""

    if not raw.strip():
        return frozenset()
    values = tuple(item.strip() for item in raw.split(","))
    if any(not value or value == "*" or _RESEARCH_PREVIEW_USER_ID.fullmatch(value) is None for value in values):
        raise ValueError("AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST contains an invalid user id")
    if len(values) != len(set(values)):
        raise ValueError("AGENTMESH_RESEARCH_PREVIEW_ALLOWLIST contains duplicate user ids")
    return frozenset(values)


def _looks_like_named_competitor_list(candidate: str) -> bool:
    normalized = re.sub(r"^(?:请|帮我|帮忙|看看|分析|研究|对比|比较|选择)+", "", candidate.strip())
    normalized = re.split(r"的|，|,|。|；|;|重点|并(?:分析|比较|给出)", normalized, maxsplit=1)[0]
    parts = [part.strip(" \t：:（）()") for part in re.split(r"\s*(?:和|与|、|[vV][sS]\.?)\s*", normalized)]
    return len(parts) >= 2 and all(1 <= len(part) <= 40 and part not in _GENERIC_SCOPE_PARTS for part in parts)


def extract_competitor_scope(text: str, *, clarification_answer: bool = False) -> str | None:
    """Extract only enough scope information to route or normalize a request."""

    value = text.strip()
    compact = re.sub(r"[\s，。！？,.!?]", "", value).lower()
    if (
        not compact
        or compact in _GENERIC_RESEARCH_REQUESTS
        or any(token in compact for token in _INVALID_SCOPE_ANSWERS)
    ):
        return None

    category = re.search(
        r"[一二三四五六七八九十两\d]+(?:款|个|类)[^，。；;]{0,60}(?:助手|工具|平台|产品|方案|应用|服务)",
        value,
    )
    if category is not None:
        return category.group(0).strip()

    candidates = [value]
    after_verb = re.search(r"(?:对比|比较|研究|分析|看看)\s*(.{1,120})", value)
    if after_verb is not None:
        candidates.insert(0, after_verb.group(1))
    for candidate in candidates:
        if _looks_like_named_competitor_list(candidate):
            return re.split(r"的|，|,|。|；|;|重点", candidate.strip(), maxsplit=1)[0].strip()

    for competitor in _KNOWN_COMPETITORS:
        if competitor.lower() in value.lower():
            return competitor
    if clarification_answer and re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+_-]{1,39}", value):
        return value
    return None


def is_competitive_research_request(raw_input: str, *, explicit_skill_name: str | None = None) -> bool:
    """Classify the narrow research-v3 preview slice without importing the retired v2 planner."""

    explicit = (explicit_skill_name or "").removeprefix("$").strip()
    if explicit:
        return explicit == "competitive-analysis"
    text = raw_input.strip()
    if any(token in text for token in _EXCLUDED_RESEARCH_INTENTS):
        return False
    has_subject = any(token in text for token in ("竞品", "竞对", "竞争产品", "对比", "比较"))
    has_goal = any(token in text for token in ("分析", "对比", "比较", "差异", "威胁", "能力", "场景", "局限", "建议"))
    return has_goal and (has_subject or extract_competitor_scope(text) is not None)


def decide_research_rollout(
    *,
    research_eligible: bool,
    configured_mode: SkillOrchestrationMode,
    active_generation: ResearchWriterGeneration,
    lifecycle_state: ResearchWriterLifecycle,
    user_id: Identifier,
    preview_allowlist: frozenset[str],
) -> ResearchRolloutDecision:
    """Choose policy without creating a Run or silently selecting another writer."""

    if not research_eligible:
        return ResearchRolloutDecision(target="v1", mode="off", reason="not_research_eligible")
    if configured_mode == SkillOrchestrationMode.OFF:
        return ResearchRolloutDecision(target="v1", mode="off", reason="orchestration_off")
    if lifecycle_state != ResearchWriterLifecycle.ACTIVE:
        reason = (
            "research_writer_draining"
            if lifecycle_state == ResearchWriterLifecycle.DRAINING
            else "research_v2_retired"
        )
        return ResearchRolloutDecision(target="v1", mode="off", reason=reason)
    if active_generation == ResearchWriterGeneration.V2:
        return ResearchRolloutDecision(target="v1", mode="off", reason="research_v2_retired")
    if configured_mode == SkillOrchestrationMode.EXECUTE:
        return ResearchRolloutDecision(target="blocked", mode="off", reason="v3_execute_not_authorized")
    if user_id not in preview_allowlist:
        return ResearchRolloutDecision(target="v1", mode="off", reason="v3_preview_not_allowlisted")
    return ResearchRolloutDecision(
        target="research-v3",
        mode="preview",
        reason="v3_preview_allowlisted",
    )


ResearchVersionInitializer = Callable[[sqlite3.Connection, AgentRun], None]


class ResearchRunCreationStore(Protocol):
    def get_research_writer_control(self) -> ResearchWriterControlV1: ...

    def claim_research_agent_run(
        self,
        run: AgentRun,
        *,
        expected_generation: ResearchWriterGeneration,
        expected_generation_epoch: int,
        expected_lifecycle_state: ResearchWriterLifecycle,
        initialize_version_state: ResearchVersionInitializer,
    ) -> tuple[AgentRun, bool]: ...


class ResearchRunCreationCoordinator:
    """Bind one proposed research Run to the current durable generation epoch."""

    def __init__(self, repository: ResearchRunCreationStore) -> None:
        self._repository = repository

    def claim(
        self,
        run: AgentRun,
        *,
        decision: ResearchRolloutDecision,
        initialize_version_state: ResearchVersionInitializer,
    ) -> tuple[AgentRun, bool]:
        generation = decision.research_generation
        if generation is None:
            raise ValueError("research creation requires a research writer decision")
        control = self._repository.get_research_writer_control()
        if control.active_generation != generation or not control.lifecycle_state.accepts_new_runs:
            raise RuntimeError("research writer generation changed before Run creation")
        controlled_run = run.model_copy(
            update={
                "orchestration_version": generation.value,
                "orchestration_mode": decision.mode,
                "writer_generation_epoch": control.generation_epoch,
            }
        )
        return self._repository.claim_research_agent_run(
            controlled_run,
            expected_generation=generation,
            expected_generation_epoch=control.generation_epoch,
            expected_lifecycle_state=control.lifecycle_state,
            initialize_version_state=initialize_version_state,
        )
