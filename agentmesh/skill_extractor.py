"""Skill extraction from repeated workflow traces.

Detects recurring patterns in user memory traces and proposes LearnedSkills
when a pattern occurs >= EXTRACTION_THRESHOLD times with successful outcomes.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from agentmesh.models import (
    LearnedSkill,
    Scope,
    SkillStatus,
    UserMemoryItem,
)

logger = logging.getLogger(__name__)

EXTRACTION_THRESHOLD = 3
SIMILARITY_THRESHOLD = 0.4


def extract_workflow_pattern(item: UserMemoryItem) -> str | None:
    """Extract the intent pattern from a workflow trace memory item."""
    if not item.source_kind.startswith("chat_workflow:"):
        return None
    return item.source_kind.replace("chat_workflow:", "")


def normalize_query(text: str) -> str:
    """Normalize a query to compare pattern similarity."""
    text = text.lower().strip()
    text = re.sub(r"\d+", "N", text)
    text = re.sub(r"\s+", " ", text)
    return text


def compute_pattern_key(intent: str, query_normalized: str) -> str:
    """Create a grouping key using the first few bigrams (positional, not sorted)."""
    bigrams: list[str] = []
    chinese_parts = re.findall(r"[一-鿿]+", query_normalized)
    for part in chinese_parts:
        for i in range(len(part) - 1):
            bigrams.append(part[i : i + 2])
    english_tokens = re.findall(r"[a-z]+", query_normalized)
    all_tokens = bigrams[:4] + english_tokens[:2]
    return f"{intent}:{'|'.join(all_tokens)}"


def detect_recurring_patterns(
    items: list[UserMemoryItem],
    threshold: int = EXTRACTION_THRESHOLD,
) -> list[dict]:
    """Find workflow patterns that recur >= threshold times.

    Returns list of dicts: {pattern_key, intent, items, count}
    """
    groups: dict[str, list[UserMemoryItem]] = defaultdict(list)

    for item in items:
        intent = extract_workflow_pattern(item)
        if intent is None:
            continue
        query_part = _extract_user_query(item.summary)
        normalized = normalize_query(query_part)
        key = compute_pattern_key(intent, normalized)
        groups[key].append(item)

    return [
        {
            "pattern_key": key,
            "intent": key.split(":")[0],
            "items": group_items,
            "count": len(group_items),
        }
        for key, group_items in groups.items()
        if len(group_items) >= threshold
    ]


def propose_skill_from_pattern(pattern: dict, user_id: str, workspace_id: str, project_id: str | None) -> LearnedSkill:
    """Create a draft LearnedSkill from a detected pattern."""
    items = pattern["items"]
    intent = pattern["intent"]

    queries = [_extract_user_query(item.summary) for item in items]
    results = [_extract_result(item.summary) for item in items]

    trigger = _synthesize_trigger(intent, queries)
    steps = _synthesize_steps(intent, results)
    validation = _synthesize_validation(results)

    return LearnedSkill(
        title=f"自动提炼：{trigger[:30]}",
        trigger_pattern=trigger,
        steps=steps,
        validation_rules=validation,
        source_workflow_ids=[item.id for item in items],
        status=SkillStatus.DRAFT,
        scope=Scope.PRIVATE,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        occurrence_count=len(items),
    )


def try_extract_skills(
    user_memory_items: list[UserMemoryItem],
    existing_skills: list[LearnedSkill],
    user_id: str,
    workspace_id: str,
    project_id: str | None = None,
) -> list[LearnedSkill]:
    """Main entry: detect patterns and propose new skills not yet extracted."""
    workflow_items = [
        item for item in user_memory_items
        if item.user_id == user_id
        and item.source_kind.startswith("chat_workflow:")
        and item.workspace_id == workspace_id
    ]
    if project_id:
        workflow_items = [item for item in workflow_items if item.project_id == project_id]

    patterns = detect_recurring_patterns(workflow_items)
    if not patterns:
        return []

    existing_source_ids = set()
    for skill in existing_skills:
        existing_source_ids.update(skill.source_workflow_ids)

    new_skills: list[LearnedSkill] = []
    for pattern in patterns:
        item_ids = {item.id for item in pattern["items"]}
        if item_ids & existing_source_ids:
            continue
        skill = propose_skill_from_pattern(pattern, user_id, workspace_id, project_id)
        new_skills.append(skill)

    return new_skills


def match_skill(query: str, skills: list[LearnedSkill]) -> LearnedSkill | None:
    """Find the best matching active skill for a user query."""
    active_skills = [s for s in skills if s.status == SkillStatus.ACTIVE]
    if not active_skills:
        return None

    query_tokens = _extract_tokens(query.lower())
    best_skill: LearnedSkill | None = None
    best_score = 0.0

    for skill in active_skills:
        trigger_tokens = _extract_tokens(skill.trigger_pattern.lower())
        if not trigger_tokens:
            continue
        overlap = len(query_tokens & trigger_tokens)
        score = overlap / max(len(trigger_tokens), 1)
        if score > best_score and score >= SIMILARITY_THRESHOLD:
            best_score = score
            best_skill = skill

    return best_skill


def _extract_tokens(text: str) -> set[str]:
    """Extract bigrams from Chinese text and whole English words."""
    tokens: set[str] = set()
    for part in re.findall(r"[一-鿿]+", text):
        for i in range(len(part) - 1):
            tokens.add(part[i : i + 2])
    tokens.update(re.findall(r"[a-z]+", text))
    return tokens


def _extract_user_query(summary: str) -> str:
    """Extract the user request part from a memory summary."""
    match = re.search(r"用户请求[：:](.+?)[；;]", summary)
    if match:
        return match.group(1).strip()
    return summary[:100]


def _extract_result(summary: str) -> str:
    """Extract the result part from a memory summary."""
    match = re.search(r"处理结果[：:](.+)", summary)
    if match:
        return match.group(1).strip()
    return ""


def _synthesize_trigger(intent: str, queries: list[str]) -> str:
    """Create a trigger pattern description from example queries."""
    common_tokens: set[str] = set()
    for query in queries:
        tokens = set(re.findall(r"[一-鿿]{2,}|[a-z]+", query.lower()))
        if not common_tokens:
            common_tokens = tokens
        else:
            common_tokens &= tokens
    if common_tokens:
        return f"{intent} 相关：{'、'.join(sorted(common_tokens)[:5])}"
    return f"{intent} 类操作"


def _synthesize_steps(intent: str, results: list[str]) -> list[str]:
    """Create steps from observed workflow results."""
    steps = [f"识别用户意图为 {intent}"]
    if any("检索" in r or "搜索" in r or "查询" in r for r in results):
        steps.append("检索相关记忆和文档")
    if any("分析" in r or "对比" in r for r in results):
        steps.append("分析和对比数据")
    steps.append("生成回答并引用来源")
    return steps


def _synthesize_validation(results: list[str]) -> list[str]:
    """Create validation rules from observed results."""
    rules = ["输出必须基于检索到的记忆内容"]
    if any("数据" in r or "指标" in r for r in results):
        rules.append("包含具体数据或指标")
    return rules
