from __future__ import annotations

import pytest

from agentmesh.agents import PersonalAgent
from agentmesh.models import (
    ContributionPoint,
    MemoryLayer,
    MemoryRelation,
    Source,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE, ensure_seed_data
from agentmesh.store import store

# In this suite A (target) is USER — the twin being asked to answer.
#              B (asker) is TEAM_LEAD — the twin asking on its owner's behalf.
TARGET = USER
ASKER = TEAM_LEAD


def _reset(*, model_enabled: bool = True) -> PersonalAgent:
    store.reset()
    ensure_seed_data(store)
    return PersonalAgent(store, llm_client=_StubLLM('建议明确业务分级并审核触发阈值。') if model_enabled else None)


def _grant(agent: PersonalAgent) -> None:
    from agentmesh.delegated_queries import DelegatedQueryService, QueryConsentRequest

    store.set_market_participation(TARGET.id, True)
    store.set_market_participation(ASKER.id, True)
    DelegatedQueryService(store).set_consent(TARGET, QueryConsentRequest(
        project_id=PROJECT.id, grantee_id=ASKER.id, enabled=True, expected_version=0, command_id='consent',
    ))


def _add_target_memory(
    title: str,
    summary: str,
    *,
    sensitivity: str = "normal",
    sources: list[Source] | None = None,
    user_id: str = TARGET.id,
) -> UserMemoryItem:
    return store.add_user_memory_item(
        UserMemoryItem(
            user_id=user_id,
            layer=MemoryLayer.MID_TERM,
            title=title,
            summary=summary,
            source_kind="promotion",
            memory_type="decision",
            sensitivity=sensitivity,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            sources=sources or [],
        )
    )


def _rich_target_memory() -> None:
    _add_target_memory(
        "大促降级预案 v3",
        "核心链路保底、非核心开关化、按 QPS 阶梯降级。",
        sources=[Source(title="降级预案文档", source_type="doc", reference="doc://plan-v3")],
    )
    _add_target_memory(
        "去年双十一降级复盘",
        "预案触发三次，阈值过激误伤购物车一次。",
        sources=[Source(title="双十一复盘", source_type="review", reference="review://1111")],
    )


QUESTION = "降级预案怎么做的"


# --- Happy path -----------------------------------------------------------

def test_standing_grant_and_rich_memory_returns_answer_with_citation_titles() -> None:
    agent = _reset()
    _rich_target_memory()
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "answered"
    assert result.answer
    assert result.confidence == "high"
    assert result.citations  # citations are exposed as titles
    assert all(isinstance(c, Source) and c.title for c in result.citations)


# --- Verbatim guard (NOT a privacy guarantee) -----------------------------
# Cross-user data flow is permitted (internal project, ADR 0003 privacy-posture):
# an LLM answer legitimately reworks the target's facts. This only guards against the
# whole raw body crossing verbatim — it does not, and need not, prevent semantic leakage.

def test_returned_answer_never_contains_target_raw_memory_body() -> None:
    agent = _reset()
    bodies = [
        "核心链路保底、非核心开关化、按 QPS 阶梯降级。",
        "预案触发三次，阈值过激误伤购物车一次。",
    ]
    _add_target_memory("大促降级预案 v3", bodies[0], sources=[Source(title="降级预案文档", source_type="doc", reference="doc://p")])
    _add_target_memory("去年双十一降级复盘", bodies[1], sources=[Source(title="双十一复盘", source_type="review", reference="review://1")])
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    serialized = result.model_dump_json()
    for body in bodies:
        assert body not in serialized


# --- Confirmation gate ----------------------------------------------------

def test_no_grant_creates_inbox_item_and_withholds_answer() -> None:
    agent = _reset()
    _rich_target_memory()

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "awaiting_confirm"
    assert result.answer is None
    assert result.inbox_item is not None
    assert result.inbox_item.user_id == TARGET.id
    # the inbox item must belong to the target's confirmation queue
    open_items = [i for i in store.inbox_items if i.item_type == "delegated_answer_confirmation"]
    assert len(open_items) == 1


def test_high_sensitivity_match_forces_confirm_even_with_standing_grant() -> None:
    agent = _reset()
    _add_target_memory(
        "降级预案内部开关清单",
        "共 42 个开关，含未公开的内部服务名。",
        sensitivity="high",
        sources=[Source(title="开关清单", source_type="doc", reference="doc://switches")],
    )
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "awaiting_confirm"
    assert result.answer is None


def test_approve_confirmation_yields_answer() -> None:
    agent = _reset()
    _rich_target_memory()
    pending = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    resolved = agent.resolve_delegated_answer(pending.inbox_item, "approve")

    assert resolved.status == "answered"
    assert resolved.answer
    assert resolved.confidence == "high"


def test_deny_confirmation_returns_nothing_to_asker() -> None:
    agent = _reset()
    _rich_target_memory()
    pending = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    resolved = agent.resolve_delegated_answer(pending.inbox_item, "deny")

    assert resolved.status == "denied"
    assert resolved.answer is None
    assert resolved.citations == []


# --- Confidence -----------------------------------------------------------

def test_sparse_memory_is_low_confidence() -> None:
    agent = _reset()
    _add_target_memory("会议里提到过降级", "只说了记得留降级口子，无细节。")
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "answered"
    assert result.confidence == "low"


def test_empty_memory_is_insufficient_with_no_citations() -> None:
    agent = _reset()
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "insufficient_evidence"
    assert result.confidence == "none"
    assert result.citations == []
    assert "信息不足" in result.answer


# --- Scope binding --------------------------------------------------------

def test_answer_never_surfaces_askers_own_memory() -> None:
    agent = _reset()
    _rich_target_memory()
    asker_secret = "ASKER-ONLY 降级预案私货不应出现"
    _add_target_memory("B 自己的降级预案笔记", asker_secret, user_id=ASKER.id)
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert asker_secret not in result.model_dump_json()


# --- Consent lifecycle ----------------------------------------------------

def test_revoke_is_prospective_and_reverts_to_confirmation_gate() -> None:
    agent = _reset()
    _rich_target_memory()
    _grant(agent)
    assert agent.answer_for_peer(ASKER, TARGET, QUESTION).status == "answered"

    from agentmesh.delegated_queries import DelegatedQueryService, QueryConsentRequest

    DelegatedQueryService(store).set_consent(TARGET, QueryConsentRequest(
        project_id=PROJECT.id, grantee_id=ASKER.id, enabled=False, expected_version=1, command_id='revoke',
    ))

    assert agent.answer_for_peer(ASKER, TARGET, QUESTION).status == "awaiting_confirm"


# --- Adoption: shadow points + lineage ------------------------------------

def test_adoption_records_shadow_point_and_derived_from_edge() -> None:
    agent = _reset()
    _rich_target_memory()
    _grant(agent)
    answer = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    point, relation = agent.adopt_delegated_answer(ASKER, TARGET, answer)

    assert isinstance(point, ContributionPoint)
    assert point.awarded_to_id == TARGET.id
    assert point.awarded_by_id == ASKER.id
    assert point.redeemable is False
    assert isinstance(relation, MemoryRelation)
    assert relation.relation_type == "derived_from"
    assert relation.to_source_id == answer.citations[0].id
    # the lineage edge is persisted and points from a memory owned by the asker
    assert any(r.id == relation.id for r in store.memory_relations)


def test_cannot_adopt_answer_without_citations() -> None:
    agent = _reset()
    _grant(agent)
    insufficient = agent.answer_for_peer(ASKER, TARGET, QUESTION)
    assert insufficient.confidence == "none"

    with pytest.raises(ValueError):
        agent.adopt_delegated_answer(ASKER, TARGET, insufficient)


# --- LLM-backed synthesis and truthful unavailable outcomes ---------------

class _StubLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.reply


class _FailingLLM:
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("llm down")


def test_llm_answer_is_used_when_llm_available() -> None:
    store.reset()
    ensure_seed_data(store)
    agent = PersonalAgent(store, llm_client=_StubLLM("A 的综合建议：分级降级 + 灰度发布。"))
    _rich_target_memory()
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "answered"
    assert result.answer == "A 的综合建议：分级降级 + 灰度发布。"
    assert result.confidence == "high"
    assert result.citations


def test_llm_insufficient_judgment_downgrades_confidence_to_none() -> None:
    store.reset()
    ensure_seed_data(store)
    agent = PersonalAgent(store, llm_client=_StubLLM("信息不足。"))
    _add_target_memory("会议里提到过降级", "只说了记得留降级口子，无细节。")  # count would say "low"
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == 'insufficient_evidence'
    assert result.confidence == "none"
    assert result.citations == []


def test_llm_failure_blocks_without_template_or_citations() -> None:
    store.reset()
    ensure_seed_data(store)
    agent = PersonalAgent(store, llm_client=_FailingLLM())
    _rich_target_memory()
    _grant(agent)

    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)

    assert result.status == "blocked"
    assert result.confidence == "none"
    assert result.citations == []
    assert '已归纳' not in result.answer


def test_unconfigured_model_cannot_answer_or_adopt_matched_memories() -> None:
    agent = _reset(model_enabled=False)
    _rich_target_memory()
    _grant(agent)
    result = agent.answer_for_peer(ASKER, TARGET, QUESTION)
    assert result.status == 'blocked' and result.confidence == 'none' and result.citations == []
    with pytest.raises(ValueError):
        agent.adopt_delegated_answer(ASKER, TARGET, result)


# --- Direct-read refusal --------------------------------------------------

def test_direct_raw_read_by_asker_is_refused_and_audited() -> None:
    agent = _reset()
    _rich_target_memory()

    before = len(store.audit_events)
    with pytest.raises(PermissionError):
        agent.read_peer_memory_directly(ASKER, TARGET)

    refusals = [e for e in store.audit_events if e.action == "refuse_direct_peer_memory_read"]
    assert len(refusals) == 1
    assert len(store.audit_events) == before + 1
