"""Seed a rich demo dataset for the Collaboration Market page.

Injects 8 mock designer/analyst/PM users, gives each of them 2-3 memory items
whose titles double as capability + need keywords, opts them into the market,
publishes each user's signal deterministically, and writes a handful of
scripted marketplace_match audit events + MARKETPLACE_MATCH board posts so the
personal-view graph and timeline have real content to render immediately —
without depending on an LLM being available.

Idempotent: running twice refreshes signals / matches in-place (deterministic
post ids) rather than duplicating rows.

Usage:
    AGENTMESH_MARKET_ENABLED=1 .venv/bin/python -m scripts.seed_market_demo
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agentmesh.auth import create_password_hash
from agentmesh.models import (
    Agent,
    AuditEvent,
    AuthCredential,
    BlackboardPost,
    BlackboardPostType,
    MemoryLayer,
    Scope,
    User,
    UserMemoryItem,
    UserRole,
)
from agentmesh.seed import PROJECT, WORKSPACE, ensure_seed_data
from agentmesh.store import store


@dataclass(frozen=True)
class DemoPerson:
    user_id: str
    name: str
    password: str
    role: UserRole
    memory_titles: tuple[str, ...]
    memory_summaries: tuple[str, ...]


DEMO_PEOPLE: tuple[DemoPerson, ...] = (
    DemoPerson(
        user_id="usr_demo_chen",
        name="陈莉",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "家电大促首屏改版方案",
            "618 大促核心指标口径与解读",
        ),
        memory_summaries=(
            "整理了 618 家电会场首屏改版的入口结构和爆品卡片布局，可与其他设计师复用。",
            "近期需要弄清楚大促核心指标（GMV/CTR/客单价）的具体口径和解读方法。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_li",
        name="李默",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "大促核心指标解读与拆解手册",
            "会场首屏 CTR 归因分析",
        ),
        memory_summaries=(
            "整理了近三年大促核心指标的口径解读与拆解方法论。",
            "针对首屏 CTR 做了归因分析，可复用给需要指标解读的同事。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_wang",
        name="王硕",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "小家电类目 Brief 模板",
            "首屏改版 A/B 实验设计",
        ),
        memory_summaries=(
            "沉淀了小家电类目 Brief 撰写的通用模板与关键要素。",
            "需要一份大促首屏改版的 A/B 实验设计参考。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_zhao",
        name="赵敏",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "A/B 实验设计与显著性判断",
            "会场分层用户画像",
        ),
        memory_summaries=(
            "熟悉 A/B 实验设计流程与显著性检验方法，可支持改版策略验证。",
            "整理了会场分层用户画像，包括新老客、价格带、活跃度维度。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_sun",
        name="孙倩",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "分层用户画像洞察",
            "视觉设计规范与组件库",
        ),
        memory_summaries=(
            "沉淀了会场分层用户画像的运营洞察，可提供画像视角建议。",
            "维护家电频道视觉设计规范与组件库，可帮设计对齐。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_zhou",
        name="周晓",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "视觉设计规范落地检查表",
            "促销素材授权与风险要点",
        ),
        memory_summaries=(
            "熟悉视觉设计规范在页面落地时的常见检查项。",
            "需要梳理促销素材外部授权与合规风险。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_lin",
        name="林俊",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "素材授权与风险审核清单",
            "跨部门审批流程指引",
        ),
        memory_summaries=(
            "沉淀了外部素材授权与风险审核清单，可支持风险咨询。",
            "整理了跨部门审批流程，可提供流程指引。",
        ),
    ),
    DemoPerson(
        user_id="usr_demo_ma",
        name="马晗",
        password="demo123",
        role=UserRole.USER,
        memory_titles=(
            "小家电 Brief 复盘",
            "首屏爆品卡片改版洞察",
        ),
        memory_summaries=(
            "近期做了小家电 Brief 的完整复盘，可分享踩坑经验。",
            "需要一份大促首屏爆品卡片改版的最新洞察参考。",
        ),
    ),
)


def _agent_id(user_id: str) -> str:
    return f"agent_{user_id}"


def _ensure_user(person: DemoPerson) -> User:
    existing = store.get_user(person.user_id)
    if existing is not None:
        return existing
    user = store.save_user(
        User(
            id=person.user_id,
            workspace_id=WORKSPACE.id,
            default_project_id=PROJECT.id,
            name=person.name,
            role=person.role.value,
            personal_agent_id=_agent_id(person.user_id),
        )
    )
    store.save_agent(
        Agent(
            id=user.personal_agent_id,
            workspace_id=WORKSPACE.id,
            name=f"{person.name} 的分身",
            agent_type="personal",
            description=f"{person.name} 的数字分身，参与自主协作市场。",
            owner_user_id=user.id,
            capabilities=["chat", "private_memory"],
        )
    )
    store.save_auth_credential(
        AuthCredential(
            id=person.user_id,
            user_id=person.user_id,
            password_hash=create_password_hash(person.password),
        )
    )
    return user


def _ensure_memory(person: DemoPerson) -> None:
    for index, (title, summary) in enumerate(zip(person.memory_titles, person.memory_summaries)):
        item_id = f"umem_demo_{person.user_id}_{index}"
        if store.get_user_memory_item(item_id) is not None:
            continue
        store.add_user_memory_item(
            UserMemoryItem(
                id=item_id,
                user_id=person.user_id,
                layer=MemoryLayer.SHORT_TERM,
                title=title,
                summary=summary,
                source_kind="demo_seed",
                workspace_id=WORKSPACE.id,
                scope=Scope.PRIVATE,
            )
        )


def _publish_signal_deterministic(person: DemoPerson) -> None:
    """Bypass the LLM path: write a signal whose need is the LAST memory title.

    That guarantees keyword_overlap will match against peers whose earlier
    memory titles share the same tokens — no LLM required for the demo.
    """
    need = person.memory_titles[-1]
    offer = "、".join(person.memory_titles[:-1]) or person.memory_titles[0]
    content = f"能力：{offer}\n可提供：可就以上话题为同事提供帮助与解答。\n需要：{need}"
    store.add_blackboard_post(
        BlackboardPost(
            id=f"bb_signal_{person.user_id}",
            task_id=f"signal_{person.user_id}",
            post_type=BlackboardPostType.MARKETPLACE_SIGNAL,
            actor=_agent_id(person.user_id),
            title=f"{person.name} 的协作信号",
            content=content,
            scope=Scope.PROJECT,
            permission="project_visible",
            read_by_agents=[_agent_id(person.user_id)],
        )
    )


# Scripted matches: (helper, needer, need_topic, status, minutes_ago)
# The current-designer user is deliberately both a helper and a needer so the
# personal graph shows incoming + outgoing edges around "me".
SCRIPTED_MATCHES: tuple[tuple[str, str, str, str, int], ...] = (
    ("usr_demo_li", "usr_current_designer", "大促核心指标口径与解读", "answered", 8),
    ("usr_demo_zhao", "usr_current_designer", "A/B 实验设计与显著性判断", "answered", 22),
    ("usr_demo_sun", "usr_current_designer", "会场分层用户画像", "awaiting_confirm", 45),
    ("usr_current_designer", "usr_demo_wang", "首屏改版 A/B 实验设计", "answered", 12),
    ("usr_current_designer", "usr_demo_ma", "首屏爆品卡片改版洞察", "answered", 30),
    ("usr_demo_lin", "usr_demo_zhou", "促销素材授权与风险要点", "answered", 18),
    ("usr_demo_wang", "usr_demo_chen", "小家电类目 Brief 复盘", "answered", 55),
    ("usr_demo_zhou", "usr_demo_lin", "跨部门审批流程指引", "denied", 70),
)


def _write_match(helper: str, needer: str, topic: str, status: str, minutes_ago: int, index: int) -> None:
    now = datetime.now(UTC)
    at = now - timedelta(minutes=minutes_ago)
    event_id = f"audit_demo_match_{index:02d}"
    event = AuditEvent(
        id=event_id,
        actor=helper,
        action="marketplace_match",
        target_type="user",
        target_id=needer,
        metadata={"helper": helper, "status": status, "need": topic},
        created_at=at,
    )
    store._upsert("audit_events", event)

    helper_user = store.get_user(helper)
    needer_user = store.get_user(needer)
    helper_name = helper_user.name if helper_user else helper
    needer_name = needer_user.name if needer_user else needer
    body = {
        "answered": f"{helper_name} 的分身给出了完整解答。",
        "awaiting_confirm": f"{helper_name} 的分身准备回答，需要 {needer_name} 确认后发送。",
        "denied": f"{helper_name} 的分身认为该请求敏感度过高，已拒绝。",
    }.get(status, "已发起代答。")
    store.add_blackboard_post(
        BlackboardPost(
            id=f"bb_match_{helper}_{needer}",
            task_id="market_activity",
            post_type=BlackboardPostType.MARKETPLACE_MATCH,
            actor=_agent_id(helper),
            title=f"协作代答：{helper_name} 帮 {needer_name} 解决「{topic[:20]}」",
            content=body,
            scope=Scope.PROJECT,
            permission="project_visible",
            read_by_agents=[_agent_id(helper)],
            created_at=at,
        )
    )


def main() -> None:
    ensure_seed_data(store)

    # Ensure built-in seed users always have credentials — ensure_seed_data
    # short-circuits unless AGENTMESH_DEMO_MODE=1 is set, but for a self-contained
    # market-demo seed we want the login to work regardless.
    from agentmesh.seed import DEFAULT_PASSWORDS, USERS

    for base_user in USERS:
        if store.get_user(base_user.id) is None:
            store.save_user(base_user)
        if store.get_auth_credential(base_user.id) is None:
            store.save_auth_credential(
                AuthCredential(
                    id=base_user.id,
                    user_id=base_user.id,
                    password_hash=create_password_hash(DEFAULT_PASSWORDS[base_user.id]),
                )
            )

    for person in DEMO_PEOPLE:
        _ensure_user(person)
        _ensure_memory(person)
        store.set_market_participation(person.user_id, True)
        _publish_signal_deterministic(person)

    # Opt the built-in seed users into the market too so they appear in the graph.
    for uid in ("usr_current_designer", "usr_team_lead", "usr_admin"):
        if store.get_user(uid) is not None:
            store.set_market_participation(uid, True)

    for index, (helper, needer, topic, status, minutes_ago) in enumerate(SCRIPTED_MATCHES):
        _write_match(helper, needer, topic, status, minutes_ago, index)

    print(f"seeded {len(DEMO_PEOPLE)} demo users")
    print(f"scripted matches: {len(SCRIPTED_MATCHES)}")
    print("done. open /market as usr_current_designer to see the graph populate.")


if __name__ == "__main__":
    main()
