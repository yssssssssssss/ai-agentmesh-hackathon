from __future__ import annotations

from agentmesh.agents import PersonalAgent
from agentmesh.models import BlackboardPost, BlackboardPostType, MemoryLayer, Scope, UserMemoryItem
from agentmesh.seed import ADMIN, PROJECT, TEAM_LEAD, USER, WORKSPACE, ensure_seed_data
from agentmesh.store import store

# B (USER) is the scout's owner / potential helper. A (TEAM_LEAD) is the needer.
HELPER = USER
NEEDER = TEAM_LEAD


class _StubLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.reply


def _reset(llm=None) -> PersonalAgent:
    store.reset()
    ensure_seed_data(store)
    return PersonalAgent(store, llm_client=llm)


def _add_memory(title: str, summary: str, *, user_id: str, sensitivity: str = "normal") -> None:
    store.add_user_memory_item(
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
        )
    )


def _signal_for(owner_id: str, need: str, capabilities: str = "大促降级预案") -> None:
    store.add_blackboard_post(
        BlackboardPost(
            id=f"bb_signal_{owner_id}",
            task_id=f"signal_{owner_id}",
            post_type=BlackboardPostType.MARKETPLACE_SIGNAL,
            actor=PersonalAgent.actor,
            title="协作信号",
            content=f"能力：{capabilities}\n可提供：答疑\n需要：{need}",
            scope=Scope.PROJECT,
            permission="project_visible",
        )
    )


# --- _match_signal (keyword pre-filter + LLM confirm) ---------------------

def test_match_signal_keyword_prefilter_blocks_unrelated() -> None:
    agent = _reset()
    # unrelated need never reaches the LLM even if the stub would say YES
    assert agent._match_signal("财务报销流程是什么", "大促降级预案、容量规划", _StubLLM("YES")) is False


def test_match_signal_llm_confirms() -> None:
    agent = _reset()
    assert agent._match_signal("大促降级预案怎么做", "大促降级预案经验", _StubLLM("YES 可以")) is True


def test_match_signal_llm_rejects() -> None:
    agent = _reset()
    assert agent._match_signal("大促降级预案怎么做", "大促降级预案经验", _StubLLM("NO 不相关")) is False


def test_match_signal_offline_falls_back_to_keyword() -> None:
    agent = _reset()
    assert agent._match_signal("大促降级预案怎么做", "大促降级预案经验", None) is True


# --- scout_and_match ------------------------------------------------------

def test_scout_matches_need_grants_consent_and_answers() -> None:
    agent = _reset()  # offline
    _add_memory("大促降级预案 v3", "核心链路保底、按 QPS 阶梯降级。", user_id=HELPER.id)
    _signal_for(NEEDER.id, "大促降级预案怎么做")

    results = agent.scout_and_match(HELPER)

    assert len(results) == 1
    needer_id, answer = results[0]
    assert needer_id == NEEDER.id
    assert answer.status == "answered"  # consent granted → non-sensitive auto-answer
    assert store.get_active_consent_grant(HELPER.id, NEEDER.id) is not None


def test_scout_publishes_a_match_event_to_the_board() -> None:
    agent = _reset()
    _add_memory("大促降级预案 v3", "核心链路保底、按 QPS 阶梯降级。", user_id=HELPER.id)
    _signal_for(NEEDER.id, "大促降级预案怎么做")

    agent.scout_and_match(HELPER)

    events = [p for p in store.blackboard_posts if p.post_type == BlackboardPostType.MARKETPLACE_MATCH]
    assert len(events) == 1
    assert events[0].scope == Scope.PROJECT
    assert NEEDER.name in events[0].title and HELPER.name in events[0].title


def test_scout_skips_own_signal() -> None:
    agent = _reset()
    _add_memory("大促降级预案 v3", "核心链路保底。", user_id=HELPER.id)
    _signal_for(HELPER.id, "大促降级预案怎么做")  # the helper's own signal

    assert agent.scout_and_match(HELPER) == []


def test_scout_skips_unsolvable_need() -> None:
    agent = _reset()
    _add_memory("大促降级预案 v3", "核心链路保底。", user_id=HELPER.id)
    _signal_for(NEEDER.id, "帮我做财务报销")  # no keyword overlap with the helper's capabilities

    assert agent.scout_and_match(HELPER) == []


def test_scout_high_sensitivity_gates_instead_of_auto_answering() -> None:
    agent = _reset()
    _add_memory("大促降级内部开关清单", "含未公开内部服务名。", user_id=HELPER.id, sensitivity="high")
    _signal_for(NEEDER.id, "大促降级预案怎么做")

    results = agent.scout_and_match(HELPER)

    assert len(results) == 1
    _, answer = results[0]
    assert answer.status == "awaiting_confirm"  # high-sensitivity still hits the gate


def test_scout_all_step_counts_triggered_answers() -> None:
    from agentmesh.marketplace import scout_all

    store.reset()
    ensure_seed_data(store)
    _add_memory("大促降级预案 v3", "核心链路保底。", user_id=HELPER.id)
    store.set_market_participation(HELPER.id, True)  # helper opts into the market
    _signal_for(NEEDER.id, "大促降级预案怎么做")

    assert scout_all(store) >= 1


def test_scout_dedup_skips_already_seen_signals() -> None:
    agent = _reset()
    _add_memory("大促降级预案 v3", "核心链路保底。", user_id=HELPER.id)
    _signal_for(NEEDER.id, "大促降级预案怎么做")

    seen: set[str] = set()
    first = agent.scout_and_match(HELPER, seen=seen)
    assert len(first) == 1
    # same unchanged signal on the next pass is skipped (no re-match / re-answer)
    second = agent.scout_and_match(HELPER, seen=seen)
    assert second == []


def test_scout_cap_limits_matches_per_run() -> None:
    agent = _reset()
    _add_memory("大促降级预案 v3", "核心链路保底。", user_id=HELPER.id)
    _signal_for(NEEDER.id, "大促降级预案怎么做")
    _signal_for(ADMIN.id, "大促降级阈值怎么设")  # a second solvable need

    results = agent.scout_and_match(HELPER, max_matches=1)
    assert len(results) == 1

