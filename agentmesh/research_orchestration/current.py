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
RESEARCH_WRITER_CONTROL_KEY = "global"
RESEARCH_WRITER_CONTROL_SEED_HASH = hashlib.sha256(
    b"research-writer-control-v1:research-v2:1"
).hexdigest()


class ResearchWriterGeneration(StrEnum):
    V2 = "research-v2"
    V3 = "research-v3"


class ResearchWriterControlV1(StrictFrozenModel):
    control_key: Literal["global"] = "global"
    active_generation: ResearchWriterGeneration
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


def decide_research_rollout(
    *,
    research_eligible: bool,
    configured_mode: SkillOrchestrationMode,
    active_generation: ResearchWriterGeneration,
    user_id: Identifier,
    preview_allowlist: frozenset[str],
) -> ResearchRolloutDecision:
    """Choose policy without creating a Run or silently selecting another writer."""

    if not research_eligible:
        return ResearchRolloutDecision(target="v1", mode="off", reason="not_research_eligible")
    if configured_mode == SkillOrchestrationMode.OFF:
        return ResearchRolloutDecision(target="v1", mode="off", reason="orchestration_off")
    if active_generation == ResearchWriterGeneration.V2:
        return ResearchRolloutDecision(target="research-v2", mode=configured_mode.value, reason="active_research_v2")
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
        if control.active_generation != generation:
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
            initialize_version_state=initialize_version_state,
        )
