"""Explicit chat skill command registry."""

from __future__ import annotations

from dataclasses import dataclass

from agentmesh.models import (
    Intent,
    MemorySearchScope,
    SkillActivationPolicy,
    SkillCapabilityType,
    SkillLifecycleStage,
    SkillSourceScope,
)


@dataclass(frozen=True)
class ChatSkillSpec:
    command: str
    title: str
    description: str
    usage: str
    intent: Intent
    placeholder: str
    aliases: tuple[str, ...] = ()
    requires_input: bool = True
    memory_search_scope: MemorySearchScope | None = None

    def to_public_dict(self) -> dict[str, object]:
        stable_name = self.command.removeprefix("$").replace(".", "-")
        return {
            "id": f"legacy-{stable_name}",
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "usage": self.usage,
            "placeholder": self.placeholder,
            "aliases": list(self.aliases),
            "requires_input": self.requires_input,
            "source": SkillSourceScope.BUILTIN.value,
            "version": "1",
            "activation_policy": SkillActivationPolicy.EXPLICIT_ONLY.value,
            "enabled": True,
            "binding_enabled": True,
            "planner_eligible": False,
            "readiness": "ready",
            "execution_readiness": "complete",
            "missing_tools": [],
            "primary_stage": SkillLifecycleStage.PLATFORM.value,
            "capability_type": SkillCapabilityType.PLATFORM.value,
            "input_kinds": [],
            "output_kinds": [],
            "side_effect": None,
            "memory_search_scope": self.memory_search_scope.value if self.memory_search_scope else None,
        }


@dataclass(frozen=True)
class ChatSkillInvocation:
    command: str
    argument: str
    spec: ChatSkillSpec | None


CHAT_SKILLS: tuple[ChatSkillSpec, ...] = (
    ChatSkillSpec(
        command="$memory.search",
        title="查询记忆/经验",
        description="检索个人、项目和团队记忆中的历史经验。",
        usage="$memory.search 618 家电会场首屏经验",
        intent=Intent.ASK_MEMORY,
        placeholder="输入要查询的项目、经验或关键词",
        aliases=("$memory", "$search.memory"),
        memory_search_scope=MemorySearchScope.AUTO,
    ),
    ChatSkillSpec(
        command="$memory.personal",
        title="查询个人记忆",
        description="仅检索当前用户的个人记忆。",
        usage="$memory.personal 618 家电会场首屏经验",
        intent=Intent.ASK_MEMORY,
        placeholder="输入要查询的个人记忆或关键词",
        memory_search_scope=MemorySearchScope.PERSONAL,
    ),
    ChatSkillSpec(
        command="$memory.project",
        title="查询项目记忆",
        description="仅检索当前对话所属项目的共享记忆。",
        usage="$memory.project 618 家电会场首屏经验",
        intent=Intent.ASK_MEMORY,
        placeholder="输入要查询的项目记忆或关键词",
        memory_search_scope=MemorySearchScope.PROJECT,
    ),
    ChatSkillSpec(
        command="$memory.team",
        title="查询团队记忆",
        description="仅检索当前用户可访问的已采纳团队记忆。",
        usage="$memory.team 618 家电会场首屏经验",
        intent=Intent.ASK_MEMORY,
        placeholder="输入要查询的团队记忆或关键词",
        memory_search_scope=MemorySearchScope.TEAM,
    ),
    ChatSkillSpec(
        command="$brief.create",
        title="生成 Brief/文档",
        description="基于当前上下文和可引用资料生成项目 Brief 草稿。",
        usage="$brief.create 生成 618 家电会场项目 Brief",
        intent=Intent.GENERATE_BRIEF,
        placeholder="描述要生成的 Brief 或方案文档",
        aliases=("$brief", "$doc.create"),
    ),
    ChatSkillSpec(
        command="$note.save",
        title="记录私有笔记",
        description="保存到当前用户的私有短期记忆，不共享给团队。",
        usage="$note.save 今天讨论确认首屏优先保证入口效率",
        intent=Intent.RECORD_PRIVATE_NOTE,
        placeholder="输入要保存的私有记录",
        aliases=("$note", "$private.save"),
    ),
    ChatSkillSpec(
        command="$research.request",
        title="请求外部资料",
        description="调用资料获取接口，补充竞品、相似项目或外部参考。",
        usage="$research.request 查找 2026 大促会场竞品资料",
        intent=Intent.REQUEST_EXTERNAL_RESEARCH,
        placeholder="输入要调研的主题",
        aliases=("$research", "$web.search"),
    ),
    ChatSkillSpec(
        command="$data.query",
        title="查询数据指标",
        description="调用 data_agent 查询点击率、转化率等项目指标。",
        usage="$data.query 查询 618 会场入口点击率",
        intent=Intent.REQUEST_DATA_QUERY,
        placeholder="输入指标、时间范围或分析问题",
        aliases=("$data", "$metric.query"),
    ),
    ChatSkillSpec(
        command="$risk.review",
        title="风险/授权检查",
        description="调用 risk_agent 检查素材授权、合规和提示词注入风险。",
        usage="$risk.review 检查这批外部素材授权风险",
        intent=Intent.REQUEST_RISK_REVIEW,
        placeholder="输入要检查的素材、来源或风险问题",
        aliases=("$risk", "$policy.review"),
    ),
    ChatSkillSpec(
        command="$memory.propose",
        title="创建候选团队记忆",
        description="把可复用结论提炼为候选团队记忆，等待审核。",
        usage="$memory.propose 首屏效率优先适用于转化目标项目",
        intent=Intent.CREATE_MEMORY_CANDIDATE,
        placeholder="输入要沉淀的经验或方法论",
        aliases=("$memory.save", "$knowledge.propose"),
    ),
    ChatSkillSpec(
        command="$system.info",
        title="查询系统/模型配置",
        description="查看当前个人 Agent 使用的模型和系统配置。",
        usage="$system.info",
        intent=Intent.ASK_SYSTEM_INFO,
        placeholder="无需额外输入",
        aliases=("$model", "$system"),
        requires_input=False,
    ),
)

_SKILL_BY_COMMAND = {
    key: spec for spec in CHAT_SKILLS for key in (spec.command, *spec.aliases)
}

_SKILL_BY_INTENT: dict[Intent, ChatSkillSpec] = {}
for _spec in CHAT_SKILLS:
    _SKILL_BY_INTENT.setdefault(_spec.intent, _spec)


def spec_for_intent(intent: Intent) -> ChatSkillSpec | None:
    return _SKILL_BY_INTENT.get(intent)


def list_chat_skills() -> list[dict[str, object]]:
    return [spec.to_public_dict() for spec in CHAT_SKILLS]


def parse_chat_skill_invocation(content: str) -> ChatSkillInvocation | None:
    text = content.strip()
    if not text.startswith("$"):
        return None
    command, _, argument = text.partition(" ")
    spec = _SKILL_BY_COMMAND.get(command)
    return ChatSkillInvocation(command=command, argument=argument.strip(), spec=spec)
