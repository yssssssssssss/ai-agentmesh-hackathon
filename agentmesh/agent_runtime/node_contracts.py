from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.models import SkillResultSource


class StandardSkillNodeResultDraftV1(BaseModel):
    """Model-owned node content; server-owned identity and accounting are added after validation."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    skill_id: str
    summary: str = Field(min_length=1, max_length=8_000)
    deliverable_markdown: str = Field(default="", max_length=60_000)
    findings: list[str] = Field(default_factory=list, max_length=100)
    recommendations: list[str] = Field(default_factory=list, max_length=100)
    delivered_output_kinds: list[str] = Field(default_factory=list, max_length=20)
    scenario_outputs: list[str] = Field(default_factory=list, max_length=100)
    completion_criteria_met: list[str] = Field(default_factory=list, max_length=100)
    sources: list[SkillResultSource] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0.5, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    degradation: str | None = Field(default=None, max_length=1_000)
