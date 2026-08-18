from __future__ import annotations

import os
from datetime import UTC, datetime

from agentmesh.auth import create_password_hash
from agentmesh.models import (
    Agent,
    AuthCredential,
    BlackboardPost,
    BlackboardPostType,
    BootstrapMetrics,
    BootstrapState,
    ChatMessage,
    ChatRole,
    ChatThread,
    ChatTurnTrace,
    CollaborationStage,
    InboxItem,
    Intent,
    MemoryItem,
    MemoryLayer,
    MemoryStatus,
    Project,
    Scope,
    Source,
    StructuredHandoffPacket,
    Task,
    TaskStatus,
    Team,
    TeamMembership,
    User,
    UserMemoryItem,
    UserRole,
    Workspace,
)
from agentmesh.permissions import capabilities_for_user
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data

WORKSPACE = Workspace(
    id="ws_home_appliance_design",
    name="家电设计组",
    description="面向家电设计团队的共享团队大脑工作空间。",
)

PROJECT = Project(
    id="prj_618_home_appliance",
    workspace_id=WORKSPACE.id,
    name="618 家电会场首页改版",
    goal="复用团队经验，提升大促会场首屏入口效率和 Brief 生成质量。",
    member_ids=["usr_current_designer", "usr_team_lead", "usr_admin"],
)

USER = User(
    id="usr_current_designer",
    workspace_id=WORKSPACE.id,
    default_project_id=PROJECT.id,
    name="何云深",
    role=UserRole.USER,
    personal_agent_id="agent_personal_current",
)

TEAM_LEAD = User(
    id="usr_team_lead",
    workspace_id=WORKSPACE.id,
    default_project_id=PROJECT.id,
    name="设计组长",
    role=UserRole.TEAM_LEAD,
    personal_agent_id="agent_personal_lead",
)

ADMIN = User(
    id="usr_admin",
    workspace_id=WORKSPACE.id,
    default_project_id=PROJECT.id,
    name="平台管理员",
    role=UserRole.ADMIN,
    personal_agent_id="agent_personal_admin",
)

USERS = [USER, TEAM_LEAD, ADMIN]
LEGACY_CURRENT_DESIGNER_NAME = "当前设计师"
DEFAULT_PASSWORDS = {
    USER.id: "designer123",
    TEAM_LEAD.id: "lead123",
    ADMIN.id: "admin123",
}

TEAM = Team(
    id="team_home_appliance_design",
    workspace_id=WORKSPACE.id,
    name="家电设计组",
    description="默认团队，用于组织成员管理与组内可见性。",
)

TEAM_MEMBERSHIPS = [
    TeamMembership(id="team_mem_user", team_id=TEAM.id, user_id=USER.id, role=UserRole.USER),
    TeamMembership(id="team_mem_lead", team_id=TEAM.id, user_id=TEAM_LEAD.id, role=UserRole.TEAM_LEAD),
    TeamMembership(id="team_mem_admin", team_id=TEAM.id, user_id=ADMIN.id, role=UserRole.ADMIN),
]

AGENTS = [
    Agent(
        id="agent_personal_current",
        workspace_id=WORKSPACE.id,
        name="我的个人 Agent",
        agent_type="personal",
        description="记录个人上下文、理解用户意图，并在需要时请求服务 Agent。",
        owner_user_id=USER.id,
        capabilities=["chat", "private_memory", "task_routing"],
    ),
    Agent(
        id="agent_personal_lead",
        workspace_id=WORKSPACE.id,
        name="组长 Agent",
        agent_type="personal",
        description="汇总组内进展、识别待审批事项，并维护团队记忆质量。",
        owner_user_id=TEAM_LEAD.id,
        capabilities=["team_digest", "memory_review", "approval_routing"],
    ),
    Agent(
        id="agent_personal_admin",
        workspace_id=WORKSPACE.id,
        name="管理员 Agent",
        agent_type="personal",
        description="管理公共 Agent 目录、审计平台配置，并观察跨组运行状态。",
        owner_user_id=ADMIN.id,
        capabilities=["agent_registry", "audit", "workspace_admin"],
    ),
    Agent(
        id="agent_research",
        workspace_id=WORKSPACE.id,
        name="research_agent",
        agent_type="research",
        description="查找团队历史经验、竞品资料和可引用来源。",
        capabilities=["project_review_lookup", "web_research"],
    ),
    Agent(
        id="agent_data",
        workspace_id=WORKSPACE.id,
        name="data_agent",
        agent_type="data",
        description="补充指标、口径和数据源线索。",
        capabilities=["metric_lookup", "data_source_check"],
    ),
    Agent(
        id="agent_risk",
        workspace_id=WORKSPACE.id,
        name="risk_agent",
        agent_type="risk",
        description="检查外部资料、素材授权和高风险共享动作。",
        capabilities=["source_risk_check", "permission_review"],
    ),
]


INITIAL_BLACKBOARD_POSTS = [
    BlackboardPost(
        id="bb_seed_research_request",
        task_id="seed_task_research",
        post_type=BlackboardPostType.REQUEST,
        actor="personal_agent",
        title="补充 618 家电会场首屏改版参考",
        content="请 research_agent 查找过往大促会场首屏结构调整的复盘结论，重点关注入口效率、信息密度和用户点击路径。",
        scope=Scope.PROJECT,
        permission="project_visible",
        read_by_agents=["research_agent", "data_agent"],
    ),
    BlackboardPost(
        id="bb_seed_research_evidence",
        task_id="seed_task_research",
        post_type=BlackboardPostType.EVIDENCE,
        actor="research_agent",
        title="过往项目复盘证据",
        content=(
            "2025 年 618 家电会场复盘显示，沉浸式头图带来视觉记忆点，但首屏核心入口点击率下降。"
            "后续方案建议将利益点、类目入口和爆品卡片前置，并减少横向滚动入口。"
        ),
        scope=Scope.PROJECT,
        permission="project_visible",
        sources=[
            Source(
                id="src_seed_research_review",
                title="2025 618 家电会场复盘",
                source_type="project_review",
                reference="project-review://2025-618-home-appliance",
            )
        ],
        read_by_agents=["personal_agent", "data_agent"],
        related_post_id="bb_seed_research_request",
    ),
    BlackboardPost(
        id="bb_seed_data_evidence",
        task_id="seed_task_research",
        post_type=BlackboardPostType.EVIDENCE,
        actor="data_agent",
        title="入口点击指标补充",
        content=(
            "data_agent 汇总近三次会场数据：当首屏入口数量控制在 6 到 8 个时，核心类目点击更稳定；"
            "超过 10 个入口后，低优先级入口曝光增加但有效点击分散。"
        ),
        scope=Scope.PROJECT,
        permission="project_visible",
        sources=[
            Source(
                id="src_seed_metrics",
                title="会场入口效率指标",
                source_type="data_source",
                reference="datasource://local_metrics/entry_efficiency",
            )
        ],
        read_by_agents=["personal_agent", "research_agent"],
        related_post_id="bb_seed_research_request",
    ),
    BlackboardPost(
        id="bb_seed_risk_review",
        task_id="seed_task_asset_check",
        post_type=BlackboardPostType.RISK,
        actor="risk_agent",
        title="外部素材授权提醒",
        content="risk_agent 发现竞品截图和第三方素材只能用于内部分析，不应直接进入对外 Brief 或设计交付物。",
        scope=Scope.PROJECT,
        permission="project_visible",
        sources=[
            Source(
                id="src_seed_risk_policy",
                title="外部素材使用规范",
                source_type="risk_rule",
                reference="risk://external-asset-policy",
            )
        ],
        read_by_agents=["personal_agent"],
    ),
    BlackboardPost(
        id="bb_seed_decision",
        task_id="seed_task_research",
        post_type=BlackboardPostType.DECISION,
        actor="personal_agent",
        title="首屏结构决策草案",
        content="建议本轮首页采用效率型结构：顶部保留主视觉，但把核心类目、PLUS 权益和爆品入口放入首屏可见范围。",
        scope=Scope.PROJECT,
        permission="project_visible",
        read_by_agents=["research_agent", "data_agent", "risk_agent"],
        related_post_id="bb_seed_research_evidence",
    ),
    BlackboardPost(
        id="bb_seed_memory_candidate",
        task_id="seed_task_memory",
        post_type=BlackboardPostType.MEMORY_CANDIDATE,
        actor="personal_agent",
        title="候选团队记忆：大促首屏入口控制",
        content="大促会场首屏入口应优先控制信息密度，超过 10 个入口会显著分散核心点击，需要进入记忆库审核。",
        scope=Scope.TEAM_CANDIDATE,
        permission="team_review_required",
        read_by_agents=["research_agent", "data_agent"],
        related_post_id="bb_seed_data_evidence",
    ),
]

DEMO_SOURCES = [
    Source(
        id="src_demo_chat_summary",
        title="今日作战室对话摘要",
        source_type="chat_thread",
        reference="chat://demo-today",
    ),
    Source(
        id="src_demo_bbs_data",
        title="BBS：入口效率指标补充",
        source_type="blackboard_post",
        reference="blackboard://bb_seed_data_evidence",
    ),
    Source(
        id="src_demo_project_archive",
        title="2025 618 家电会场项目归档",
        source_type="project_archive",
        reference="project-archive://2025-618-home-appliance",
    ),
]

INITIAL_INBOX_ITEMS = [
    InboxItem(
        id="inbox_demo_decision_review",
        title="确认首屏结构决策草案",
        summary="个人 Agent 根据 research_agent 和 data_agent 的帖子整理出效率型首屏方案，需要你确认是否进入 Brief。",
        item_type="decision_review",
        scope=Scope.PRIVATE,
        user_id=USER.id,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
    ),
    InboxItem(
        id="inbox_demo_risk_review",
        title="外部素材授权需要确认",
        summary="risk_agent 标记了竞品截图和第三方素材：可用于内部分析，不建议直接进入对外交付物。",
        item_type="risk_review",
        scope=Scope.PRIVATE,
        user_id=USER.id,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
    ),
    InboxItem(
        id="inbox_demo_tool_approval",
        title="等待批准资料获取 Agent",
        summary="个人 Agent 判断还缺少 2026 年大促会场参考，后续可接入真实资料获取 Agent 后由这里发起授权。",
        item_type="tool_call_approval",
        scope=Scope.PRIVATE,
        user_id=USER.id,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
    ),
]

INITIAL_USER_MEMORY_ITEMS = [
    UserMemoryItem(
        id="umem_demo_short_today",
        user_id=USER.id,
        layer=MemoryLayer.SHORT_TERM,
        title="今天讨论了 618 首屏入口密度",
        summary="用户关注平台能否直接给出项目建议，而不是让用户处理大量 Agent 事务；首屏应以平台 chat 为核心。",
        source_kind="chat",
        memory_type="daily_summary",
        memory_date=datetime.now(UTC).date(),
        scope=Scope.PRIVATE,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        sources=[DEMO_SOURCES[0]],
    ),
    UserMemoryItem(
        id="umem_demo_project_decision",
        user_id=USER.id,
        layer=MemoryLayer.MID_TERM,
        title="项目记忆：大促首页优先效率型结构",
        summary="618 家电会场首页改版优先复用过往复盘：核心类目、PLUS 权益、爆品入口需要进入首屏可见范围。",
        source_kind="promotion",
        memory_type="decision",
        memory_date=datetime.now(UTC).date(),
        scope=Scope.PRIVATE,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        sources=[DEMO_SOURCES[1]],
    ),
    UserMemoryItem(
        id="umem_demo_project_archive",
        user_id=USER.id,
        layer=MemoryLayer.LONG_TERM,
        title="项目归档：2025 618 家电会场复盘",
        summary="沉浸式头图提升视觉记忆点，但会挤压核心入口效率；后续大促项目应限制首屏入口数量并明确优先级。",
        source_kind="archive",
        memory_type="project_archive",
        memory_date=datetime.now(UTC).date(),
        scope=Scope.PRIVATE,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        sources=[DEMO_SOURCES[2]],
    ),
]

INITIAL_MEMORY_ITEMS = [
    MemoryItem(
        id="mem_demo_team_accepted_entry_density",
        title="团队记忆：首屏入口数量控制",
        summary="大促会场首屏入口建议控制在 6 到 8 个，超过 10 个会分散核心类目点击。",
        memory_type="data",
        scope=Scope.TEAM_ACCEPTED,
        status=MemoryStatus.ACCEPTED,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        sources=[DEMO_SOURCES[1]],
    ),
    MemoryItem(
        id="mem_demo_team_candidate_asset_policy",
        title="团队候选：竞品截图仅用于内部分析",
        summary="竞品截图和第三方素材可作为内部研究证据，不应直接进入对外 Brief 或设计交付物。",
        memory_type="risk",
        scope=Scope.TEAM_CANDIDATE,
        status=MemoryStatus.PROPOSED,
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
        sources=[DEMO_SOURCES[2]],
    ),
]


def list_agents(repository: SQLiteStore) -> list[Agent]:
    saved_by_id = {agent.id: agent for agent in repository.agents}
    merged = [saved_by_id.pop(agent.id, agent) for agent in AGENTS]
    return merged + list(saved_by_id.values())


def list_workspaces(repository: SQLiteStore) -> list[Workspace]:
    saved_by_id = {workspace.id: workspace for workspace in repository.workspaces}
    merged = [saved_by_id.pop(WORKSPACE.id, WORKSPACE)]
    return merged + list(saved_by_id.values())


def list_projects(repository: SQLiteStore, workspace_id: str | None = None) -> list[Project]:
    saved_by_id = {project.id: project for project in repository.projects}
    merged = [saved_by_id.pop(PROJECT.id, PROJECT)] + list(saved_by_id.values())
    if workspace_id is None:
        return merged
    return [project for project in merged if project.workspace_id == workspace_id]


def demo_mode_enabled() -> bool:
    return os.getenv("AGENTMESH_DEMO_MODE", "").strip() == "1"


def ensure_base_workspace_data(repository: SQLiteStore) -> None:
    if repository.get_workspace(WORKSPACE.id) is None:
        repository.save_workspace(WORKSPACE)
    if repository.get_project(PROJECT.id) is None:
        repository.save_project(PROJECT)
    if repository.get_team(TEAM.id) is None:
        repository.save_team(TEAM)


def ensure_user_default_membership(repository: SQLiteStore, user: User) -> None:
    ensure_base_workspace_data(repository)
    project = repository.get_project(user.default_project_id)
    if project is not None and project.workspace_id == user.workspace_id and user.id not in project.member_ids:
        project.member_ids.append(user.id)
        repository.save_project(project)
    if user.workspace_id == TEAM.workspace_id and not repository.list_team_memberships(
        team_id=TEAM.id, user_id=user.id
    ):
        repository.save_team_membership(
            TeamMembership(team_id=TEAM.id, user_id=user.id, role=user.role)
        )


def ensure_demo_seed_data(repository: SQLiteStore) -> None:
    if not demo_mode_enabled():
        return
    ensure_tool_seed_data(repository, granted_by="system")
    ensure_base_workspace_data(repository)
    if repository.get_workspace(WORKSPACE.id) is None:
        repository.save_workspace(WORKSPACE)
    if repository.get_project(PROJECT.id) is None:
        repository.save_project(PROJECT)
    if repository.get_team(TEAM.id) is None:
        repository.save_team(TEAM)
    for membership in TEAM_MEMBERSHIPS:
        if repository.get_team_membership(membership.id) is None:
            repository.save_team_membership(membership)
    for user in USERS:
        existing_user = repository.get_user(user.id)
        if existing_user is None:
            repository.save_user(user)
        elif user.id == USER.id and existing_user.name == LEGACY_CURRENT_DESIGNER_NAME:
            repository.save_user(existing_user.model_copy(update={"name": USER.name}))
        if repository.get_auth_credential(user.id) is None:
            repository.save_auth_credential(
                AuthCredential(
                    id=user.id,
                    user_id=user.id,
                    password_hash=create_password_hash(DEFAULT_PASSWORDS[user.id]),
                )
            )


def ensure_seed_data(repository: SQLiteStore) -> None:
    """Seed deterministic demo identities when the test/demo environment opts in."""
    ensure_demo_seed_data(repository)


def ensure_initial_blackboard_data(repository: SQLiteStore) -> None:
    for post in INITIAL_BLACKBOARD_POSTS:
        if repository.get_blackboard_post(post.id) is None:
            for source in post.sources:
                if repository.get_source(source.id) is None:
                    repository.add_source(source)
            repository.add_blackboard_post(post)


def ensure_demo_data(repository: SQLiteStore) -> None:
    for source in DEMO_SOURCES:
        if repository.get_source(source.id) is None:
            repository.add_source(source)
    for item in INITIAL_INBOX_ITEMS:
        if repository.get_inbox_item(item.id) is None:
            repository.add_inbox_item(item)
    for item in INITIAL_USER_MEMORY_ITEMS:
        if repository.get_user_memory_item(item.id) is None:
            repository.add_user_memory_item(item)
    for item in INITIAL_MEMORY_ITEMS:
        if repository.get_memory_item(item.id) is None:
            repository.add_memory_item(item)


def list_users(repository: SQLiteStore) -> list[User]:
    saved_by_id = {user.id: user for user in repository.users}
    merged = [saved_by_id.pop(user.id, user) for user in USERS]
    return merged + list(saved_by_id.values())


def bootstrap_state(repository: SQLiteStore, user: User = USER) -> BootstrapState:
    ensure_seed_data(repository)
    agents = list_agents(repository)
    now = datetime.now(UTC)
    return BootstrapState(
        workspace=WORKSPACE,
        project=PROJECT,
        user=user,
        users=list_users(repository),
        teams=repository.list_teams(workspace_id=user.workspace_id),
        team_memberships=repository.list_team_memberships(user_id=user.id),
        agents=agents,
        capabilities=capabilities_for_user(user, repository.permission_policy_rules),
        metrics=BootstrapMetrics(
            personal_activity_count=len(
                [log for log in repository.list_personal_activity() if log.project_id == PROJECT.id]
            ),
            external_activity_count=len(
                [log for log in repository.list_external_activity() if log.project_id == PROJECT.id]
            ),
            memory_candidate_count=len(
                [
                    item
                    for item in repository.memory_items
                    if item.scope == Scope.TEAM_CANDIDATE and item.project_id == PROJECT.id
                ]
            ),
            source_count=len(repository.sources),
            inbox_open_count=len(
                [
                    item
                    for item in repository.inbox_items
                    if item.project_id == PROJECT.id
                    and item.status != "resolved"
                    and (item.status != "snoozed" or item.snooze_until is None or item.snooze_until <= now)
                ]
            ),
        ),
    )


def _graph_demo_sources() -> list[Source]:
    return [
        Source(
            id="src_graph_demo_2025_review",
            title="2025 年 618 家电会场复盘",
            source_type="project_review",
            reference="review://home-appliance-618-2025",
        ),
        Source(
            id="src_graph_demo_2024_category_day",
            title="2024 年家电超级品类日",
            source_type="project_review",
            reference="review://home-appliance-category-day-2024",
        ),
        Source(
            id="src_graph_demo_core_experience",
            title="团队经验：首屏核心入口优先",
            source_type="team_experience",
            reference="memory://team/home-appliance-entry-priority",
        ),
        Source(
            id="src_graph_demo_entry_metrics",
            title="首页营销入口点击数据",
            source_type="data_connector",
            reference="internal://analytics/home-appliance-entry-ctr-90d",
        ),
        Source(
            id="src_graph_demo_liming_peer",
            title="李明的数字员工 · 协作贡献",
            source_type="peer_contribution",
            reference="peer://liming/home-appliance-2025-review",
        ),
    ]


def _graph_demo_assistant_content() -> str:
    return """项目理解
家电设计师 · 618 会场改版 · 首屏结构决策 · 基于本人及团队已授权工作知识分析。

任务分析
1. 理解任务：识别当前处于 618 会场改版准备阶段，本次需要解决的是首屏结构与核心入口效率问题。
2. 查找相似项目：找到 3 个相关项目：2025 年 618 家电会场复盘、2024 年家电超级品类日等。
3. 检索已确认团队经验：找到 2 条已确认经验，与首屏入口效率和沉浸式头图使用相关。
4. 查询近期业务数据：调用数据查询 Skill，读取近 90 天首页营销入口点击数据。数据范围：近 90 天 · 当前用户有权访问。
5. 邀请数字员工补充判断：李明的数字员工补充项目经验，王晨的数字员工补充入口数据并提醒确认数据统计口径。
6. 本次依据摘要：3 个相似项目 · 2 条已确认经验 · 近 90 天业务数据 · 2 位数字员工贡献。

核心建议
综合历史项目与近 90 天数据，我的建议是：2026 年 618 家电会场首屏应优先保证核心入口效率。沉浸式头图能增强氛围，但会下压重点商品与活动入口、拉低首屏点击。推荐采用效率型楼层结构，并把重点品类入口固定在首屏可视区。

本次工作过程
- 在团队 Wiki 与项目库检索「618 家电会场 首屏」，命中 3 个高相似度会场、2 条团队经验。
- 调用「数据查询 Skill」，取回首页营销入口近 90 天点击数据。
- 李明的数字人：补充 2025 年复盘，沉浸式头图降低首屏核心入口可见性。
- 王晨的数字人：补充首屏入口点击数据，量化点击率下降约 11%。
- 综合历史结论与近 90 天数据，判断入口型会场应优先保证首屏核心入口效率，并据此生成 2026 Brief。

技术执行记录
- 知识检索：wiki.search(query="618家电会场 首屏", top_k=8) · 命中 3 项目 / 2 经验。
- Skill 调用：skill.marketing_entry_metrics(scene="home", range="90d") · 200 OK · 1.2s。
- 分身协作：peer.request(to=["李明","王晨"], type="evidence") · 2 responses。
- 生成：compose_brief(evidence=6, template="project_kickoff") · tokens 3.1k。

引用资料详情
1. 2025 年 618 家电会场复盘（历史项目 · 相似度 92%）
   - 项目背景：2025 年 618 家电会场首页采用沉浸式头图方案，强调品牌氛围与视觉冲击。
   - 核心问题：沉浸式头图占据首屏主要空间，重点商品与活动入口被下压到折叠线以下。
   - 设计方案：首屏以整屏头图 + 轮播为主，核心入口楼层排在头图之后。
   - 结果数据：首屏核心入口点击率环比下降 11%，用户到达重点品类的路径变长。
   - 与当前任务的关联：直接对应本次「首屏是否沿用沉浸式头图」的核心决策，是最相似的历史样本。

2. 2024 年家电超级品类日（历史项目 · 相似度 78%）
   - 项目背景：2024 年家电超级品类日首页采用效率型楼层结构，头图精简。
   - 核心问题：需要在有限首屏内平衡氛围表达与多品类入口。
   - 设计方案：精简头图 + 核心品类入口楼层前置，氛围元素下沉到楼层背景。
   - 结果数据：首屏入口点击率相比沉浸式方案高出约 9%，转化路径更短。
   - 与当前任务的关联：为「效率型楼层结构」提供正向历史依据。

3. 团队经验：首屏核心入口优先（家电设计组 · 团队经验）
   - 经验结论：入口型营销会场首屏应优先保证核心入口的可见性与点击效率，氛围表达服从入口效率。
   - 来源项目：2025 618 家电会场复盘、2024 家电超级品类日。
   - 适用范围：入口型营销活动会场（会场首页、品类日首页）。
   - 最近验证时间：最近验证：2025 年 618 大促，数据再次支持该结论。
   - 引用项目：2024 家电超级品类日、PLUS 会员日活动页、清凉家电会场（引用中）。

4. 首页营销入口点击数据（数据查询 Skill · 近 90 天）
   - 数据范围：家电会场首页营销入口（头图、重点品类、活动楼层）的曝光与点击。
   - 核心指标：首屏核心入口点击率，沉浸式头图方案 -11%；效率型楼层首屏点击率，对比沉浸式方案 +9%；重点品类入口到达率，效率型更优 +7%。
   - 关键结论：效率型楼层结构在首屏核心入口点击与重点品类到达上均优于沉浸式头图方案。
   - 数据时间：统计区间：近 90 天（含 2025 618 大促期）。
   - 口径说明：首屏 = 进入页面首个可视区；点击率 = 入口点击 UV / 首屏曝光 UV。

5. 李明的数字员工 · 协作贡献（来自已授权的项目经验）
   - 角色和擅长领域：李明 · 家电设计组；擅长：营销会场设计、历史项目复盘。
   - 引用经验：2025 年 618 家电会场复盘；✓ 已确认经验；经验结论：沉浸式头图能够增强会场氛围，但可能压缩核心商品和活动入口的首屏可见性。
   - 具体贡献：结合当前 618 项目以品类分流和重点商品承接为主要目标，建议避免整屏沉浸式头图，优先保证核心入口首屏可见。
   - 知识来源：来源项目：2025 年 618 家电会场；确认人：李明；验证时间：2025 年 7 月；适用范围：会场首页首屏结构决策。本次仅调用李明已授权共享的工作知识，不读取私人对话和未授权项目。

2026 年 618 家电会场首页设计 Brief
- 项目目标：在 618 大促期间提升家电会场首屏的核心入口效率，兼顾品牌氛围与转化路径。
- 历史背景：
  · 2025 年 618 采用沉浸式头图，首屏视觉氛围强，但核心入口首屏可见性下降。
  · 2024 年家电超级品类日使用效率型楼层，核心入口点击表现更稳定。
- 核心问题：沉浸式头图占据首屏后，重点商品与活动入口被下压，首屏核心入口点击率下滑。
- 设计原则：
  1. 首屏优先保证核心入口的可见性与点击效率。
  2. 沉浸式头图需结合入口点击数据谨慎使用，控制首屏占比。
  3. 采用效率型楼层结构，保留重点商品入口在首屏可达。
- 设计方向：
  · 首屏采用「精简头图 + 核心入口楼层」组合。
  · 重点品类入口固定在首屏可视区，减少下滑成本。
  · 氛围表达迁移到二屏及楼层背景，避免挤占入口。
- 数据支撑：
  · 2025 年沉浸式头图方案首屏核心入口点击率环比下降 11%。
  · 效率型楼层在 2024 品类日首屏入口点击率高出 9%。

后续建议
- 继续补充重点商品入口方案。
- 对比两种首屏结构。
- 创建后续任务。""".strip()


def ensure_graph_demo_data(repository: SQLiteStore) -> None:
    """Inject multi-agent collaboration mock data for the graph view."""
    from datetime import timedelta

    base_time = datetime(2026, 6, 26, 10, 0, 0, tzinfo=UTC)
    thread_title = "2026 年 618 家电会场首页改版"

    thread = repository.get_chat_thread("thread_graph_demo")
    if thread is None:
        thread = ChatThread(
            id="thread_graph_demo",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=USER.id,
            title=thread_title,
            created_at=base_time,
            updated_at=base_time,
        )
        repository.save_chat_thread(thread)
    elif thread.title == "618 家电首屏历史经验查询":
        thread = thread.model_copy(update={"title": thread_title})
        repository.save_chat_thread(thread)

    sources = _graph_demo_sources()
    assistant_content = _graph_demo_assistant_content()
    messages_by_id = {message.id: message for message in repository.list_thread_messages(thread.id)}
    if "msg_graph_demo_user" not in messages_by_id:
        repository.add_chat_message(
            ChatMessage(
                id="msg_graph_demo_user",
                thread_id=thread.id,
                role=ChatRole.USER,
                content="我要做今年 618 家电会场首页改版，帮我查找过去有没有类似项目经验，并给出首屏设计建议。",
                scope=Scope.PRIVATE,
                created_at=base_time + timedelta(seconds=1),
            )
        )
    existing_assistant = messages_by_id.get("msg_graph_demo_assistant")
    if (
        existing_assistant is None
        or "2026 年 618 家电会场首页设计 Brief" not in existing_assistant.content
        or len(existing_assistant.sources) < len(sources)
    ):
        repository.add_chat_message(
            ChatMessage(
                id="msg_graph_demo_assistant",
                thread_id=thread.id,
                role=ChatRole.ASSISTANT,
                content=assistant_content,
                scope=Scope.PRIVATE,
                sources=sources,
                created_at=base_time + timedelta(seconds=2),
            )
        )
    traces_by_id = {trace.id: trace for trace in repository.list_thread_turn_traces(thread.id)}
    existing_trace = traces_by_id.get("trace_graph_demo_initial")
    if existing_trace is None or len(existing_trace.sources) < len(sources):
        repository.add_chat_turn_trace(
            ChatTurnTrace(
                id="trace_graph_demo_initial",
                thread_id=thread.id,
                user_message_id="msg_graph_demo_user",
                assistant_message_id="msg_graph_demo_assistant",
                intent=Intent.ASK_MEMORY,
                source="demo_seed",
                selected_workflow="persisted_demo_conversation",
                persisted=True,
                llm_used=False,
                confidence=1.0,
                actual_provider="seed",
                provider_mode="fallback",
                latency_ms=0.0,
                steps=[
                    "received_user_message",
                    "searched_memory",
                    "external_research_requested",
                    "evidence_received",
                    "synthesized",
                    "brief_drafted",
                ],
                sources=sources,
                created_at=base_time + timedelta(seconds=3),
            )
        )

    if repository.get_task("task_graph_demo_1") is not None:
        return

    # --- Task 1: memory search → research → evidence → digest ---
    task1 = Task(
        id="task_graph_demo_1",
        thread_id=thread.id,
        intent=Intent.ASK_MEMORY,
        status=TaskStatus.COMPLETED,
        collaboration_stage=CollaborationStage.COMPLETED,
        current_owner_agent_id="agent_personal_current",
        title="查询 618 家电会场首屏历史经验",
        steps=["memory_searched", "external_research_requested", "evidence_received", "synthesized"],
        created_at=base_time,
    )
    repository.save_task(task1)

    post1_request = BlackboardPost(
        id="bb_graph_demo_1_req",
        task_id=task1.id,
        post_type=BlackboardPostType.REQUEST,
        actor="agent_personal_current",
        title="请求：618 家电首屏设计经验",
        content="用户查询 618 家电会场首屏历史经验，本地记忆无命中，需要外部 Agent 补充研究资料。",
        scope=Scope.PROJECT,
        permission="project_visible",
        collaboration_stage=CollaborationStage.EXECUTION,
        current_owner_agent_id="agent_research",
        handoff=StructuredHandoffPacket(
            goal="获取 618 家电首屏的历史数据与经验",
            current_result="本地记忆无相关条目",
            done_when="提供至少 2 条历史首屏设计经验",
            next_owner_agent_id="agent_research",
        ),
        created_at=base_time + timedelta(seconds=5),
    )
    repository.add_blackboard_post(post1_request)

    post1_evidence = BlackboardPost(
        id="bb_graph_demo_1_evi",
        task_id=task1.id,
        post_type=BlackboardPostType.EVIDENCE,
        actor="agent_research",
        title="证据：618 家电首屏历史数据",
        content="根据外部数据源查询，2024 年 618 家电会场首屏点击率最高的模块是'爆品直降'（CTR 12.3%），其次是'品类精选'（CTR 9.7%）。2023 年首屏改版后用户停留时长提升 18%。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post1_request.id,
        collaboration_stage=CollaborationStage.REVIEW,
        sources=[Source(id="src_demo_1", title="618 大促复盘数据", source_type="data_connector", reference="internal://analytics/618-2024")],
        created_at=base_time + timedelta(seconds=30),
    )
    repository.add_blackboard_post(post1_evidence)

    post1_risk = BlackboardPost(
        id="bb_graph_demo_1_risk",
        task_id=task1.id,
        post_type=BlackboardPostType.RISK,
        actor="agent_risk_scanner",
        title="风险：数据时效性提醒",
        content="2024 年数据可能不适用于 2026 年会场，用户行为模式可能已变化。建议结合最新 A/B 测试验证。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post1_evidence.id,
        collaboration_stage=CollaborationStage.REVIEW,
        created_at=base_time + timedelta(seconds=45),
    )
    repository.add_blackboard_post(post1_risk)

    post1_digest = BlackboardPost(
        id="bb_graph_demo_1_digest",
        task_id=task1.id,
        post_type=BlackboardPostType.DIGEST,
        actor="agent_personal_current",
        title="摘要：首屏经验综合结论",
        content="综合历史数据和风险评估，建议首屏保留'爆品直降'核心模块，同时新增 A/B 测试验证 2026 年用户偏好变化。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post1_evidence.id,
        collaboration_stage=CollaborationStage.COMPLETED,
        created_at=base_time + timedelta(minutes=1),
    )
    repository.add_blackboard_post(post1_digest)

    # --- Task 2: brief generation with handoff chain ---
    task2 = Task(
        id="task_graph_demo_2",
        thread_id=thread.id,
        intent=Intent.GENERATE_BRIEF,
        status=TaskStatus.COMPLETED,
        collaboration_stage=CollaborationStage.COMPLETED,
        current_owner_agent_id="agent_personal_current",
        title="生成首屏改版设计 Brief",
        steps=["brief_drafted", "review_requested", "approved", "memory_candidate_created"],
        created_at=base_time + timedelta(minutes=5),
    )
    repository.save_task(task2)

    post2_decision = BlackboardPost(
        id="bb_graph_demo_2_dec",
        task_id=task2.id,
        post_type=BlackboardPostType.DECISION,
        actor="agent_personal_current",
        title="决策：启动首屏改版 Brief",
        content="基于前序经验查询结果，决定立即生成设计 Brief，方向为保留爆品直降+新增品类推荐位。",
        scope=Scope.PROJECT,
        permission="project_visible",
        collaboration_stage=CollaborationStage.DISCUSSION,
        created_at=base_time + timedelta(minutes=5, seconds=10),
    )
    repository.add_blackboard_post(post2_decision)

    post2_handoff = BlackboardPost(
        id="bb_graph_demo_2_handoff",
        task_id=task2.id,
        post_type=BlackboardPostType.HANDOFF,
        actor="agent_personal_current",
        title="交接：Brief 审核给组长",
        content="Brief 初稿已完成，交接给设计组长进行质量审核。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post2_decision.id,
        collaboration_stage=CollaborationStage.REVIEW,
        handoff=StructuredHandoffPacket(
            goal="审核 Brief 质量与方向",
            current_result="Brief 初稿已包含爆品直降模块+品类推荐位",
            done_when="组长确认 Brief 方向无误",
            next_owner_agent_id="agent_personal_lead",
        ),
        created_at=base_time + timedelta(minutes=6),
    )
    repository.add_blackboard_post(post2_handoff)

    post2_evidence = BlackboardPost(
        id="bb_graph_demo_2_evi",
        task_id=task2.id,
        post_type=BlackboardPostType.EVIDENCE,
        actor="agent_personal_lead",
        title="审核通过：Brief 方向确认",
        content="组长确认 Brief 方向合理，建议补充预算约束说明。已批准进入执行阶段。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post2_handoff.id,
        collaboration_stage=CollaborationStage.COMPLETED,
        created_at=base_time + timedelta(minutes=8),
    )
    repository.add_blackboard_post(post2_evidence)

    post2_memory = BlackboardPost(
        id="bb_graph_demo_2_mem",
        task_id=task2.id,
        post_type=BlackboardPostType.MEMORY_CANDIDATE,
        actor="agent_personal_current",
        title="记忆候选：首屏改版 Brief 经验",
        content="618 首屏改版 Brief 生成流程：经验查询→风险评估→初稿→组长审核→批准。该流程耗时约 8 分钟。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post2_evidence.id,
        collaboration_stage=CollaborationStage.COMPLETED,
        created_at=base_time + timedelta(minutes=9),
    )
    repository.add_blackboard_post(post2_memory)

    # --- Task 3: ongoing task with blocked state ---
    task3 = Task(
        id="task_graph_demo_3",
        thread_id=thread.id,
        intent=Intent.ASK_MEMORY,
        status=TaskStatus.WAITING_EXTERNAL_AGENT,
        collaboration_stage=CollaborationStage.BLOCKED,
        current_owner_agent_id="agent_research",
        title="查询竞品首屏布局方案",
        steps=["memory_searched", "external_research_requested"],
        created_at=base_time + timedelta(minutes=15),
    )
    repository.save_task(task3)

    post3_request = BlackboardPost(
        id="bb_graph_demo_3_req",
        task_id=task3.id,
        post_type=BlackboardPostType.REQUEST,
        actor="agent_personal_current",
        title="请求：竞品首屏布局数据",
        content="需要外部 Agent 提供天猫、苏宁等竞品 618 首屏布局方案对比分析。",
        scope=Scope.PROJECT,
        permission="project_visible",
        collaboration_stage=CollaborationStage.EXECUTION,
        current_owner_agent_id="agent_research",
        handoff=StructuredHandoffPacket(
            goal="收集竞品首屏布局方案",
            current_result="暂无竞品数据",
            done_when="提供至少 3 个竞品首屏布局方案对比",
            next_owner_agent_id="agent_research",
        ),
        created_at=base_time + timedelta(minutes=15, seconds=5),
    )
    repository.add_blackboard_post(post3_request)

    post3_correction = BlackboardPost(
        id="bb_graph_demo_3_cor",
        task_id=task3.id,
        post_type=BlackboardPostType.CORRECTION,
        actor="agent_risk_scanner",
        title="修正：需补充竞品时间范围",
        content="请求未指定时间范围，建议明确为 2025-2026 年竞品数据，避免获取过旧信息。",
        scope=Scope.PROJECT,
        permission="project_visible",
        related_post_id=post3_request.id,
        collaboration_stage=CollaborationStage.BLOCKED,
        created_at=base_time + timedelta(minutes=16),
    )
    repository.add_blackboard_post(post3_correction)
