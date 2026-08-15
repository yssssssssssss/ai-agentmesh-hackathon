from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from agentmesh.models import Intent, Source
from agentmesh.provider_status import provider_metadata


class AcquisitionRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    intent: Intent
    workspace_id: str
    project_id: str
    user_id: str
    task_id: str
    request_post_id: str


class AcquisitionResult(BaseModel):
    actor: str
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    sources: list[Source] = Field(default_factory=list)
    permission: str = "project_visible"
    metadata: dict[str, str] = Field(default_factory=dict)


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
