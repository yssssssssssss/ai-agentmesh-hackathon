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
    InboxItem,
    MemoryLayer,
    Scope,
    User,
    UserMemoryItem,
    UserRole,
)
from agentmesh.seed import PROJECT, WORKSPACE, ensure_demo_data, ensure_seed_data
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
    for index, (title, summary) in enumerate(zip(person.memory_titles, person.memory_summaries, strict=False)):
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


def _publish_signal_deterministic(person: DemoPerson, minutes_ago: int = 0) -> None:
    """Bypass the LLM path: write a signal whose need is the LAST memory title.

    That guarantees keyword_overlap will match against peers whose earlier
    memory titles share the same tokens — no LLM required for the demo.

    ``minutes_ago`` back-dates the signal so the global activity feed interleaves
    signals with matches instead of stacking all "刚刚发布" signals on top.
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
            created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        )
    )


# Scripted matches: (helper, needer, need_topic, status, minutes_ago, answer)
# The current-designer user is deliberately both a helper and a needer so the
# personal graph shows incoming + outgoing edges around "me". `answer` is the
# abstracted reply the helper's twin produced from its own private memory — it is
# what a viewer sees when opening the record. awaiting_confirm / denied carry no
# answer body on purpose: the gateway hasn't released one yet.
SCRIPTED_MATCHES: tuple[tuple[str, str, str, str, int, str], ...] = (
    (
        "usr_demo_li", "usr_current_designer", "大促核心指标口径与解读", "answered", 8,
        "关于大促核心指标口径，给你一份可直接对齐的结论：\n"
        "· GMV：以「下单成交额」口径统计，含未支付但已锁库存的预售定金期订单，退款在 T+1 冲减；不要用「支付成交额」跨会场对比。\n"
        "· CTR：分母是会场楼层的曝光 PV（卡片进入视口即计），分子是卡片点击 UV，按人去重；首屏和非首屏要分开看，混算会稀释首屏表现。\n"
        "· 客单价：GMV / 成交用户数，注意剔除套装拆单，否则大促期会被虚高。\n"
        "口径打架时以数据平台「大促指标字典 v3」为准，我把常用的几个已经核对过。",
    ),
    (
        "usr_demo_zhao", "usr_current_designer", "A/B 实验设计与显著性判断", "answered", 22,
        "首屏改版的 A/B 实验，建议按这个框架落地：\n"
        "1) 目标与指标：主指标锁定首屏点击转化率（CTR→加购），护栏指标放页面稳定性与跳出率，避免只看单点提升。\n"
        "2) 分流与样本量：按设备 ID 哈希分流保证均衡；以基线 CTR 4%、最小可检测提升 5%、双尾 α=0.05、power=0.8 估算，单组约需 3.2 万曝光 UV，大促首日即可跑满。\n"
        "3) 显著性判断：跑满预估样本再看，不要中途反复瞄结果（会抬高假阳性）；用双样本比例检验，p<0.05 且置信区间不跨 0 才算显著。\n"
        "4) 上线策略：显著为正则全量，持平或负向则回滚并记录到实验档案。",
    ),
    (
        "usr_current_designer", "usr_demo_sun", "首屏改版 A/B 实验设计", "awaiting_confirm", 45,
        "",
    ),
    (
        "usr_current_designer", "usr_demo_wang", "首屏改版 A/B 实验设计", "answered", 12,
        "给你我这边首屏改版沉淀的实验设计要点：\n"
        "· 改版假设写清楚——我们这次验证的是「爆品卡片前置是否提升加购」，不要一次动太多变量。\n"
        "· 对照组保持旧版首屏，实验组只换卡片排序与信息密度，其余不动，方便归因。\n"
        "· 主指标用首屏加购率，观察窗口至少覆盖一个完整大促日（含晚高峰），别只看白天。\n"
        "· 我上次踩的坑：素材加载慢会拖累实验组 CTR，记得先压素材体积再上实验，否则结论失真。",
    ),
    (
        "usr_current_designer", "usr_demo_ma", "首屏爆品卡片改版洞察", "answered", 30,
        "首屏爆品卡片改版，我这边的复盘洞察给你参考：\n"
        "· 爆品卡片「大图 + 到手价 + 利益点标签」三段式转化最好，比纯商品图高约 12% 点击。\n"
        "· 到手价一定要直接算好展示，让用户在首屏做「叠加计算」会明显掉转化。\n"
        "· 卡片数量控制在首屏 4-6 张，再多会挤压核心入口、拉低整体效率。\n"
        "· 沉浸式头图慎用：视觉记忆点强，但会把首屏核心入口往下压，效率型会场得不偿失。",
    ),
    (
        "usr_demo_lin", "usr_demo_zhou", "促销素材授权与风险要点", "answered", 18,
        "促销素材的授权与风险，按这份清单自查基本能覆盖：\n"
        "· 外部 IP / 明星肖像：必须有书面授权且在授权期内，注意授权渠道是否含「电商大促」场景。\n"
        "· 字体与配乐：确认商用授权，免费字体也要看是否允许商用，这块最容易被投诉。\n"
        "· 比价与「全网最低」话术：涉及《广告法》绝对化用语风险，一律替换为「活动价」「限时价」。\n"
        "· 素材留档：授权文件和素材版本一一对应存档，出问题能快速举证。",
    ),
    (
        "usr_demo_wang", "usr_demo_chen", "小家电类目 Brief 复盘", "answered", 55,
        "小家电类目 Brief 的复盘，我提炼了几条可复用的经验：\n"
        "· Brief 开头先写清「这次要打的核心人群 + 主推卖点」，别一上来堆功能参数。\n"
        "· 竞品对标只选 2-3 个真正同价位段的，对标太多会失焦。\n"
        "· 视觉调性用 3 个关键词框定（如「轻量 / 高级 / 亲和」），比长段描述更好落地。\n"
        "· 我踩过的坑：Brief 里不写清尺寸与安全区，交付时反复返工，记得附版式规范。",
    ),
    (
        "usr_demo_zhou", "usr_demo_lin", "跨部门审批流程指引", "denied", 70,
        "",
    ),
)


def _write_match(
    helper: str, needer: str, topic: str, status: str, minutes_ago: int, answer: str, index: int
) -> None:
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
        "awaiting_confirm": f"{helper_name} 的分身已准备好答案，涉及较敏感的记忆，需要 {needer_name} 确认后才会发送。",
        "denied": f"{helper_name} 的分身判断该请求敏感度过高，已拒绝代答，未透露任何内容。",
    }.get(status, answer or f"{helper_name} 的分身给出了完整解答。")
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


def _publish_current_designer_signal(minutes_ago: int = 5) -> None:
    """Publish a deterministic signal for the logged-in demo designer (usr_current_designer).

    The built-in seed user isn't a DemoPerson, and the publish worker runs on a long
    interval during a frozen demo — so seed the signal directly. The need mirrors the
    scripted outgoing match topic so the request/help story stays self-consistent.
    """
    uid = "usr_current_designer"
    user = store.get_user(uid)
    if user is None:
        return
    content = (
        "能力：大促首页效率型结构、618 家电会场复盘、首屏入口密度\n"
        "可提供：可就大促首屏改版与入口结构为同事提供建议。\n"
        "需要：首屏改版 A/B 实验设计"
    )
    store.add_blackboard_post(
        BlackboardPost(
            id=f"bb_signal_{uid}",
            task_id=f"signal_{uid}",
            post_type=BlackboardPostType.MARKETPLACE_SIGNAL,
            actor=user.personal_agent_id,
            title=f"{user.name} 的协作信号",
            content=content,
            scope=Scope.PROJECT,
            permission="project_visible",
            read_by_agents=[user.personal_agent_id],
            created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        )
    )


def _seed_confirmation_gate_inbox() -> None:
    """Back the awaiting_confirm timeline row with a real confirmation inbox item.

    Scenario: 孙倩's twin asked 当前设计师's twin to answer「首屏改版 A/B 实验设计」;
    the request tripped the confirmation gate, so it waits in 当前设计师's inbox. This
    makes the gate operable in the demo — the logged-in designer can approve/deny it
    and watch the answer get released. The question matches 当前设计师's own memory so
    approving synthesizes a real answer.
    """
    designer = store.get_user("usr_current_designer")
    if designer is None:
        return
    store.add_inbox_item(
        InboxItem(
            id="inbox_demo_delegated_confirm",
            title="确认代答请求",
            summary="孙倩 的分身请求由你的分身代答：「首屏改版 A/B 实验设计」。",
            item_type="delegated_answer_confirmation",
            scope=Scope.PRIVATE,
            user_id=designer.id,
            workspace_id=designer.workspace_id,
            metadata={
                "asker_id": "usr_demo_sun",
                "target_id": designer.id,
                "question": "首屏改版 A/B 实验设计",
                "reason": "no_standing_consent",
            },
        )
    )


def main() -> None:
    ensure_seed_data(store)
    # Also seed the built-in designer's private memory + inbox baseline (normally
    # injected at app startup under DEMO_MODE). Running this seed after a store.reset()
    # would otherwise leave usr_current_designer with 0 memories, breaking the
    # presence tile and the confirmation-gate answer synthesis.
    ensure_demo_data(store)

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

    for index, person in enumerate(DEMO_PEOPLE):
        _ensure_user(person)
        _ensure_memory(person)
        store.set_market_participation(person.user_id, True)
        # Stagger signal timestamps (3, 15, 27, … min ago) so the global activity
        # feed interleaves signals with the scripted matches rather than stacking
        # all signals on top as "刚刚".
        _publish_signal_deterministic(person, minutes_ago=3 + index * 12)

    # Opt the built-in seed users into the market too so they appear in the graph.
    for uid in ("usr_current_designer", "usr_team_lead", "usr_admin"):
        if store.get_user(uid) is not None:
            store.set_market_participation(uid, True)

    _publish_current_designer_signal()
    _seed_confirmation_gate_inbox()

    for index, (helper, needer, topic, status, minutes_ago, answer) in enumerate(SCRIPTED_MATCHES):
        _write_match(helper, needer, topic, status, minutes_ago, answer, index)

    print(f"seeded {len(DEMO_PEOPLE)} demo users")
    print(f"scripted matches: {len(SCRIPTED_MATCHES)}")
    print("done. open /market as usr_current_designer to see the graph populate.")


if __name__ == "__main__":
    main()
