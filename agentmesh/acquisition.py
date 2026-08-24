from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field, field_validator, model_validator

from agentmesh.models import Intent, Source
from agentmesh.provider_status import provider_metadata


class AcquisitionQuery(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    question_ids: list[str] = Field(default_factory=list, max_length=20)


class ProviderCallRecord(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    operation: str = Field(min_length=1, max_length=80)
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: str = Field(pattern=r"^(success|error)$")
    latency_ms: int = Field(ge=0)
    result_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=120)


class AcquisitionRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    intent: Intent
    workspace_id: str
    project_id: str
    user_id: str
    task_id: str
    request_post_id: str
    question_queries: list[AcquisitionQuery] = Field(default_factory=list, max_length=4)


class AcquiredEvidenceItem(BaseModel):
    source_id: str = Field(min_length=1, max_length=120)
    content_provider: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(min_length=1, max_length=8192)
    retrieved_at: datetime
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    truncated: bool = False
    risk_flags: list[str] = Field(default_factory=list, max_length=10)
    question_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("retrieved_at")
    @classmethod
    def require_aware_retrieval_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_content_hash(self) -> AcquiredEvidenceItem:
        if hashlib.sha256(self.excerpt.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("content_hash must match excerpt")
        if self.risk_flags != sorted(set(self.risk_flags)):
            raise ValueError("risk_flags must be ordered and unique")
        if self.question_ids != list(dict.fromkeys(self.question_ids)):
            raise ValueError("question_ids must be ordered and unique")
        if self.truncated != ("truncated" in self.risk_flags):
            raise ValueError("truncated evidence must carry the matching risk flag")
        return self


class AcquisitionResult(BaseModel):
    actor: str
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    sources: list[Source] = Field(default_factory=list)
    source_evidence: list[AcquiredEvidenceItem] = Field(default_factory=list, max_length=100)
    provider_calls: list[ProviderCallRecord] = Field(default_factory=list, max_length=20)
    permission: str = "project_visible"
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_evidence(self) -> AcquisitionResult:
        source_ids = {source.id for source in self.sources}
        evidence_ids = [item.source_id for item in self.source_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("source_evidence source IDs must be unique")
        if not set(evidence_ids).issubset(source_ids):
            raise ValueError("source_evidence must reference returned sources")
        return self


class AcquisitionAgent(Protocol):
    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult: ...


class MockAcquisitionAgent:
    actor = "mock_research_agent"

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        source = Source(
            title="2025 618 家电会场复盘",
            source_type="project_review",
            reference="review://home-appliance-618-2025",
        )
        return AcquisitionResult(
            actor=self.actor,
            title="找到相似项目经验",
            content=(
                "2025 年 618 家电会场曾尝试沉浸式头图，但复盘显示首屏核心入口点击下降。"
                "后续方案改为效率型楼层结构，并保留重点商品入口。"
            ),
            sources=[source],
            metadata={
                **provider_metadata(
                    requested_provider="research",
                    actual_provider="mock",
                    mode="fallback",
                    fallback_reason="no_real_provider_configured",
                    latency_ms=0.0,
                ),
                "request_post_id": request.request_post_id,
            },
        )


class ExternalAcquisitionConnector:
    actor = "external_acquisition_agent"

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        raise NotImplementedError("External acquisition is provided by another project.")


PROMPT_INJECTION_SIGNALS = (
    "忽略之前",
    "忽略以上",
    "忽略所有指令",
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "系统提示词",
    "developer message",
    "执行 rm",
    "rm -rf",
    "泄露",
    "api key",
)


def detect_prompt_injection(content: str) -> list[str]:
    lowered = content.lower()
    return [signal for signal in PROMPT_INJECTION_SIGNALS if signal in lowered]


HIGH_RISK_TOOL_SIGNALS = (
    "批量抓取",
    "批量爬取",
    "抓取所有",
    "下载所有",
    "批量下载",
    "内网",
    "写入团队记忆",
    "自动发布",
    "删除",
    "delete",
    "crawl all",
    "download all",
    "intranet",
)


def detect_high_risk_tool_call(content: str) -> list[str]:
    lowered = content.lower()
    return [signal for signal in HIGH_RISK_TOOL_SIGNALS if signal in lowered]
