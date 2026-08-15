import type { ShareScope } from '../store/DemoContext'

/* ============ 当前用户与空间 ============ */
export const CURRENT_USER = {
  name: '林知夏',
  role: '体验设计师',
  space: '家电设计组',
  domains: ['营销会场', '首页体验', '导购场景'],
  project: '2026 年 618 家电会场首页改版',
}

/* ============ 首页：数字人身份 ============ */
export const DIGITAL_PROFILE = {
  personalKnowledge: 24,
  teamSkills: 6,
  monthlyCollab: 8,
  /** 数字人支持过的项目数(数字人管理 · 知识与权限累计指标) */
  projectsSupported: 6,
}

/* ============ 数字人管理：数字人档案 ============
 * 数字人自身的身份信息，独立于用户 ERP 身份。
 * 引用 CURRENT_USER 中与真实组织关系一致的字段，避免重复维护。
 */
export interface AgentProfile {
  name: string
  /** 侧栏入口卡 / 二级导航副标题 */
  assistantTitle: string
  /** 角色定位 */
  rolePositioning: string
  /** 服务对象 */
  serviceTargets: string[]
  /** 所属空间(= CURRENT_USER.space) */
  space: string
  /** 主要领域 */
  domains: string[]
  online: boolean
}
export const AGENT_PROFILE: AgentProfile = {
  name: `${CURRENT_USER.name}的数字人`,
  assistantTitle: '体验设计助手',
  rolePositioning: '体验设计师 · 营销会场方向',
  serviceTargets: ['家电设计组设计师', '618 家电会场项目组', '发起协作的同事数字人'],
  space: CURRENT_USER.space,
  domains: CURRENT_USER.domains,
  online: true,
}

/* ============ 首页：最近理解了我 ============ */
export interface Understanding {
  id: string
  text: string
  /** 形成这条理解的依据(供「查看形成依据」展开) */
  basis: string
  /** 依据来源出处 */
  source: string
}
export const UNDERSTANDINGS: Understanding[] = [
  {
    id: 'u-1',
    text: '你近期主要关注会场首屏入口效率。',
    basis: '近 5 次 618 会场对话中，你反复强调「首屏入口效率优先」。',
    source: '618 会场对话 · 工作台',
  },
  {
    id: 'u-2',
    text: '你更倾向使用数据和历史案例支持设计决策。',
    basis: '多次决策中你要求补充历史案例与近 90 天数据后再下结论。',
    source: '工作洞察 · 项目复盘',
  },
  {
    id: 'u-3',
    text: '你正在建立营销会场的项目启动方法。',
    basis: '消息活动日历复盘中，你主导整理了一套项目启动方法。',
    source: '项目复盘记录',
  },
]

/* ============ 首页：今日工作(旧) ============ */
export interface TodoItem {
  id: string
  title: string
  status: 'done' | 'doing' | 'pending'
  to?: string
}
export const TODAY_WORK: TodoItem[] = [
  { id: 't-1', title: '618 家电会场首页设计 Brief', status: 'doing', to: '/workspace' },
  { id: 't-2', title: '补充 2026 年首屏入口数据', status: 'done' },
  { id: 't-3', title: '补充消息活动日历项目复盘结果', status: 'pending', to: '/knowledge?tab=pending' },
]

/* ============ 首页:今日优先事项 ============
 * 2 件事,由数字员工根据当前工作和历史项目主动排序:
 *   1. 当前项目关键任务(618,进行中)
 *   2. 复盘补充(历史项目,可能形成知识候选)
 * 工作理解统一放在下方「待确认的理解」模块处理,避免信息重复。
 */
export type PriorityTone = 'mint' | 'knowledge' | 'collab' | 'remind'

export interface PriorityItem {
  id: string
  /** L1 标题:一句话说明该做什么 */
  title: string
  /** 上下文:数字人为什么把它排在今天 */
  context: string
  /** 情境标签:「当前项目」「历史项目」「工作理解」 */
  tag: string
  tone: PriorityTone
  /** 主 CTA 文案 */
  cta: string
  /** 跳转目标;'#understanding' 时首页内滚动至 UnderstandingList */
  to: string
}

export const PRIORITY_ITEMS: PriorityItem[] = [
  {
    id: 'p-brief',
    title: '继续 618 会场首页设计 Brief',
    context: '数字员工已整合历史项目、团队经验与近期数据，等待你继续确认首屏方案。',
    tag: '当前项目',
    tone: 'mint',
    cta: '继续项目',
    to: '/workspace',
  },
  {
    id: 'p-review',
    title: '确认活动日历项目复盘结论',
    context: '项目结果已完成整理，数字员工提炼出 1 条候选经验，等待你确认后沉淀。',
    tag: '待确认经验',
    tone: 'knowledge',
    cta: '去确认',
    to: '/insights',
  },
]

/* ============ 工作台：对话 ============ */
export interface Conversation {
  id: string
  title: string
  project: string
  status: '进行中' | '已完成' | '待确认'
  updated: string
  group: '进行中' | '今天' | '昨天' | '本周'
  active?: boolean
}
export const CONVERSATIONS: Conversation[] = [
  { id: 'conv-1', title: '618 家电会场首页改版', project: '2026 618 家电会场', status: '进行中', updated: '刚刚', group: '进行中', active: true },
  { id: 'conv-2', title: '首屏入口点击口径确认', project: '2026 618 家电会场', status: '已完成', updated: '今天 14:20', group: '今天' },
  { id: 'conv-3', title: '2024 品类日楼层结构梳理', project: '2024 超级品类日', status: '已完成', updated: '昨天 18:05', group: '昨天' },
  { id: 'conv-4', title: '导购卡首屏数量测试', project: '导购场景优化', status: '已完成', updated: '本周一', group: '本周' },
]

/** 数字人回答正文 */
export const WORKSPACE_ANSWER =
  '综合历史项目与近 90 天数据，我的建议是：2026 年 618 家电会场首屏应优先保证核心入口效率。沉浸式头图能增强氛围，但会下压重点商品与活动入口、拉低首屏点击。推荐采用效率型楼层结构，并把重点品类入口固定在首屏可视区。'

/** 分析过程摘要（折叠态一行展示的要点） */
export const WORKSPACE_ANALYSIS_SUMMARY = [
  '找到 3 个相似项目',
  '检索 2 条团队经验',
  '调用 1 个数据查询 Skill',
  '获得 2 位同事数字分身的补充',
]

/** 分析过程步骤（对话内展开，用户语言，不含底层命令） */
export const WORKSPACE_ANALYSIS_STEPS = [
  '正在理解当前任务',
  '正在检索相似项目',
  '正在读取团队经验',
  '正在请求相关数字分身补充',
  '正在整合数据和项目判断',
  '已形成设计建议',
]

/** 右侧面板：本次工作过程（结构化展开） */
export const WORKSPACE_ANALYSIS = {
  retrieved: '在团队 Wiki 与项目库检索「618 家电会场 首屏」，命中 3 个高相似度会场、2 条团队经验。',
  skill: '调用「数据查询 Skill」，取回首页营销入口近 90 天点击数据。',
  peers: [
    { name: '李明的数字人', contribution: '补充 2025 年复盘：沉浸式头图降低首屏核心入口可见性。' },
    { name: '王晨的数字人', contribution: '补充首屏入口点击数据，量化点击率下降约 11%。' },
  ],
  conclusion: '综合历史结论与近 90 天数据，判断入口型会场应优先保证首屏核心入口效率，并据此生成 2026 Brief。',
}

/* 工作台：技术详情（右侧面板过程视图内二级折叠，默认收起） */
export const WORKSPACE_TECH_LOG = [
  { label: '知识检索', detail: 'wiki.search(query="618家电会场 首屏", top_k=8) · 命中 3 项目 / 2 经验' },
  { label: 'Skill 调用', detail: 'skill.marketing_entry_metrics(scene="home", range="90d") · 200 OK · 1.2s' },
  { label: '分身协作', detail: 'peer.request(to=["李明","王晨"], type="evidence") · 2 responses' },
  { label: '生成', detail: 'compose_brief(evidence=6, template="project_kickoff") · tokens 3.1k' },
]

/* ============ 工作台：引用来源（内联引用 + 右侧详情面板） ============ */
export type RefKind = 'project' | 'experience' | 'data' | 'peer'

export interface ProjectDetail {
  background: string
  problem: string
  solution: string
  result: string
  relation: string
}
export interface ExperienceDetail {
  conclusion: string
  sourceProjects: string[]
  scope: string
  lastVerified: string
  citedBy: string[]
}
export interface DataMetric {
  label: string
  value: string
  delta?: string
}
export interface DataDetail {
  range: string
  metrics: DataMetric[]
  conclusion: string
  time: string
  caliber: string
}
export interface PeerDetail {
  field: string
  citedExperience: string
  contribution: string
  knowledgeSource: string
}

export type WorkspaceRef =
  | { id: string; kind: 'project'; title: string; chip: string; detail: ProjectDetail }
  | { id: string; kind: 'experience'; title: string; chip: string; detail: ExperienceDetail }
  | { id: string; kind: 'data'; title: string; chip: string; detail: DataDetail }
  | { id: string; kind: 'peer'; title: string; chip: string; detail: PeerDetail }

export const WORKSPACE_REFERENCES: WorkspaceRef[] = [
  {
    id: 'ref-2025',
    kind: 'project',
    title: '2025 年 618 家电会场复盘',
    chip: '历史项目 · 相似度 92%',
    detail: {
      background: '2025 年 618 家电会场首页采用沉浸式头图方案，强调品牌氛围与视觉冲击。',
      problem: '沉浸式头图占据首屏主要空间，重点商品与活动入口被下压到折叠线以下。',
      solution: '首屏以整屏头图 + 轮播为主，核心入口楼层排在头图之后。',
      result: '首屏核心入口点击率环比下降 11%，用户到达重点品类的路径变长。',
      relation: '直接对应本次「首屏是否沿用沉浸式头图」的核心决策，是最相似的历史样本。',
    },
  },
  {
    id: 'ref-2024',
    kind: 'project',
    title: '2024 年家电超级品类日',
    chip: '历史项目 · 相似度 78%',
    detail: {
      background: '2024 年家电超级品类日首页采用效率型楼层结构，头图精简。',
      problem: '需要在有限首屏内平衡氛围表达与多品类入口。',
      solution: '精简头图 + 核心品类入口楼层前置，氛围元素下沉到楼层背景。',
      result: '首屏入口点击率相比沉浸式方案高出约 9%，转化路径更短。',
      relation: '为「效率型楼层结构」提供正向历史依据。',
    },
  },
  {
    id: 'ref-data',
    kind: 'data',
    title: '首页营销入口点击数据',
    chip: '数据查询 Skill · 近 90 天',
    detail: {
      range: '家电会场首页营销入口（头图、重点品类、活动楼层）的曝光与点击。',
      metrics: [
        { label: '首屏核心入口点击率', value: '沉浸式头图方案', delta: '-11%' },
        { label: '效率型楼层首屏点击率', value: '对比沉浸式方案', delta: '+9%' },
        { label: '重点品类入口到达率', value: '效率型更优', delta: '+7%' },
      ],
      conclusion: '效率型楼层结构在首屏核心入口点击与重点品类到达上均优于沉浸式头图方案。',
      time: '统计区间：近 90 天（含 2025 618 大促期）。',
      caliber: '口径：首屏 = 进入页面首个可视区；点击率 = 入口点击 UV / 首屏曝光 UV。',
    },
  },
  {
    id: 'ref-liming',
    kind: 'peer',
    title: '李明的数字员工 · 协作贡献',
    chip: '来自已授权的项目经验',
    detail: {
      field: '李明 · 家电设计组\n擅长：营销会场设计、历史项目复盘。',
      citedExperience: '2025 年 618 家电会场复盘\n✓ 已确认经验\n经验结论：沉浸式头图能够增强会场氛围，但可能压缩核心商品和活动入口的首屏可见性。',
      contribution: '结合当前 618 项目以品类分流和重点商品承接为主要目标，建议避免整屏沉浸式头图，优先保证核心入口首屏可见。',
      knowledgeSource: '来源项目：2025 年 618 家电会场\n确认人：李明\n验证时间：2025 年 7 月\n适用范围：会场首页首屏结构决策\n\n本次仅调用李明已授权共享的工作知识，不读取私人对话和未授权项目。',
    },
  },
]

/** 核心结论所依据的团队经验（单独引用，演示 experience 详情） */
export const CORE_EXPERIENCE_REF: WorkspaceRef = {
  id: 'ref-exp',
  kind: 'experience',
  title: '团队经验：首屏核心入口优先',
  chip: '家电设计组 · 团队经验',
  detail: {
    conclusion: '入口型营销会场首屏应优先保证核心入口的可见性与点击效率，氛围表达服从入口效率。',
    sourceProjects: ['2025 618 家电会场复盘', '2024 家电超级品类日'],
    scope: '入口型营销活动会场（会场首页、品类日首页）。',
    lastVerified: '最近验证：2025 年 618 大促，数据再次支持该结论。',
    citedBy: ['2024 家电超级品类日', 'PLUS 会员日活动页', '清凉家电会场（引用中）'],
  },
}

/* ============ 会场 Brief 内容 ============ */
export const BRIEF = {
  title: '2026 年 618 家电会场首页设计 Brief',
  goal: '在 618 大促期间提升家电会场首屏的核心入口效率，兼顾品牌氛围与转化路径。',
  history: [
    '2025 年 618 采用沉浸式头图，首屏视觉氛围强，但核心入口首屏可见性下降。',
    '2024 年家电超级品类日使用效率型楼层，核心入口点击表现更稳定。',
  ],
  problem: '沉浸式头图占据首屏后，重点商品与活动入口被下压，首屏核心入口点击率下滑。',
  principles: [
    '首屏优先保证核心入口的可见性与点击效率。',
    '沉浸式头图需结合入口点击数据谨慎使用，控制首屏占比。',
    '采用效率型楼层结构，保留重点商品入口在首屏可达。',
  ],
  direction: [
    '首屏采用「精简头图 + 核心入口楼层」组合。',
    '重点品类入口固定在首屏可视区，减少下滑成本。',
    '氛围表达迁移到二屏及楼层背景，避免挤占入口。',
  ],
  data: [
    '2025 年沉浸式头图方案首屏核心入口点击率环比下降 11%。',
    '效率型楼层在 2024 品类日首屏入口点击率高出 9%。',
  ],
}

/* ============ 待我确认 · 知识候选(来自"消息活动日历改版"项目复盘) ============ */
/**
 * 只有 已完成项目 经过复盘、补充结果后才会形成的知识候选。
 * 2026 年 618 家电会场处于准备阶段,不进入本页(见修改文档 §4.2)。
 */
export const NEW_KNOWLEDGE = {
  id: 'cand-msgcal',
  title: '页面空间应根据用户使用价值动态分配',
  conclusion:
    '当多个模块竞争有限的首屏空间时,应结合用户任务、点击效率和业务必要性分配展示权重。对低频但必须保留的模块,可以收缩展示面积并保留基础入口,将释放的空间优先提供给高频核心任务模块。',
  status: 'candidate' as KnowledgeStatus,
  suggestedTypeLabel: '决策方法',
  sourceProject: '消息活动日历改版',
  contributor: '林知夏',
  formedAt: '项目复盘完成后',
  formationMethod: '项目数据 + 设计决策 + 实际落地结果',
  // 形成依据 · 项目问题
  problem:
    '活动日历点击效率较低,但占用了较高的页面空间;消息卡片点击效率最高,却没有获得与其价值匹配的首屏权重。',
  // 形成依据 · 原始数据
  rawData: [
    { label: '消息卡片 CTR', value: '10.53%' },
    { label: '活动日历 CTR', value: '0.50%' },
    { label: 'Feeds 大包裹 CTR', value: '2.01%' },
  ],
  // 形成依据 · 项目决策
  decisions: ['缩窄活动日历', '保留活动日历基础入口', '释放首屏空间', '提升消息卡片展示权重'],
  // 形成依据 · 项目结果(如没有真实提升数据,不编造比例)
  result:
    '改版方案已经按预期落地,活动日历基础功能得到保留,释放的首屏空间用于提升消息卡片展示权重。项目负责人已确认最终上线方案和结果记录。',
  // 适用范围
  scope: ['首页', '消息中心', '多模块竞争首屏空间的页面', '同时存在高频核心任务与低频必要入口的场景'],
  // 限制条件
  limitation:
    '点击率不是唯一判断依据。承担强业务提醒、合规或必要通知的模块,即使点击较低,也需要保留基本可达性。',
  // AI 建议(第二步 / 第三步默认值)
  recommendType: 'decision_method' as KnowledgeType,
  recommendVisibility: 'team' as Visibility,
  recommendVisibilityLabel: '家电设计组',
  recommendScope: 'group' as ShareScope,
}

/* 我的知识 · 旧样例已在三 Tab 改版中移除,数据来源统一为 KNOWLEDGE_ASSETS / SHARE_EVENTS(见下方) */

/* ============================================================
 * 我的知识 · 新数据模型(见修改文档 §12)
 * 三 Tab: 知识资产 / 待我确认 / 共享与引用
 * 所有知识必须来源于真实工作或项目复盘;AI 生成的方案建议不能直接称为知识。
 * ============================================================ */

export type KnowledgeStatus = 'candidate' | 'confirmed' | 'archived'

export type Visibility = 'private' | 'project' | 'team' | 'custom'

export type KnowledgeType =
  | 'design_rule'
  | 'decision_method'
  | 'project_experience'
  | 'data_insight'
  | 'workflow_method'
  | 'risk_boundary'

export type UsageEventType =
  | 'shared'
  | 'reuse_requested'
  | 'reused'
  | 'feedback_received'
  | 'update_requested'

export type UsageStatus = 'unused' | 'cited' | 'has_feedback'

export const KNOWLEDGE_TYPE_LABELS: Record<KnowledgeType, string> = {
  design_rule: '设计规范',
  decision_method: '决策方法',
  project_experience: '项目经验',
  data_insight: '数据经验',
  workflow_method: '流程方法',
  risk_boundary: '风险与边界',
}

export const VISIBILITY_LABELS: Record<Visibility, string> = {
  private: '仅自己',
  project: '当前项目',
  team: '已共享给团队',
  custom: '自定义范围',
}

export interface KnowledgeCitation {
  who: string
  project: string
  time: string
  purpose?: string
}

export interface KnowledgeAsset {
  id: string
  title: string
  conclusion: string
  type: KnowledgeType
  scope: string
  sourceProject: string
  contributor: string
  verified: string
  visibility: Visibility
  /** team 时可以进一步说明团队名 */
  visibilityDetail?: string
  citedBy: number
  updated: string
  hasNewFeedback?: boolean
  /** 详情抽屉需要的展开信息 */
  problem?: string
  evidence?: string[]
  limitation?: string
  citations?: KnowledgeCitation[]
  /** 系统生成的记号:是否由候选沉淀而来,便于在首位标注"刚沉淀" */
  justConfirmed?: boolean
}

/** 已确认的知识资产(4 条,来自修改文档 §8.4) */
export const KNOWLEDGE_ASSETS: KnowledgeAsset[] = [
  {
    id: 'ka-tag',
    title: '活动标签信息层级规范',
    conclusion: '活动标签按照"利益点—品类—时间"排列,弱化次要信息,提升首屏扫读效率。',
    type: 'design_rule',
    scope: '营销活动标签',
    sourceProject: '618 家电会场',
    contributor: '林知夏',
    verified: '已确认',
    visibility: 'private',
    citedBy: 0,
    updated: '3 天前',
    problem:
      '早期活动标签排列以"品类—利益点—时间"为主,用户扫读时最先看到的是次要品类信息,而不是最有决策价值的利益点。',
    evidence: [
      '618 家电会场对比测试:利益点前置的标签扫读时长下降约 18%',
      '首屏可读标签数量从 3 提升到 4',
    ],
    limitation: '仅适用于营销活动标签,不适用于工具型或状态型入口标签。',
    citations: [],
  },
  {
    id: 'ka-floor',
    title: '会场楼层优先级模型',
    conclusion: '根据用户任务、入口价值和转化贡献排列楼层顺序,核心品类入口优先展示。',
    type: 'decision_method',
    scope: '入口型营销会场',
    sourceProject: '2024 超级品类日',
    contributor: '林知夏',
    verified: '已通过项目复盘',
    visibility: 'team',
    visibilityDetail: '家电设计组',
    citedBy: 4,
    updated: '1 月前',
    problem: '大促会场楼层通常按品类堆叠,忽略了不同入口对首屏转化的贡献差异。',
    evidence: [
      '2024 超级品类日:核心楼层前置后首屏入口点击率 +9%',
      '重点品类入口到达率 +7%',
    ],
    limitation: '仅适用于入口型会场;导购型或推荐流页面不适用。',
    citations: [
      { who: '王晨的数字人', project: 'PLUS 会员日会场', time: '2 天前', purpose: '首屏楼层优先级排布' },
      { who: '赵敏的数字人', project: '小家电专场', time: '2 周前' },
      { who: '孙浩的数字人', project: '清凉家电会场', time: '3 周前' },
      { who: '李明的数字人', project: '2024 家电超级品类日复盘', time: '1 月前' },
    ],
  },
  {
    id: 'ka-guide',
    title: '导购卡片首屏承载数量',
    conclusion: '首屏导购卡建议控制在 4–6 个,超过后容易造成点击分散和决策成本上升。',
    type: 'data_insight',
    scope: '首屏导购卡',
    sourceProject: '导购场景优化',
    contributor: '林知夏',
    verified: '已通过测试',
    visibility: 'team',
    visibilityDetail: '家电设计组',
    citedBy: 3,
    updated: '2 周前',
    hasNewFeedback: true,
    problem: '首屏导购卡数量过多时用户在多张卡片间反复对比,决策链变长、跳出率上升。',
    evidence: [
      '导购场景优化 A/B 测试:控制在 4–6 张时点击 CTR 更稳定',
      '超过 6 张后单卡片点击稀释明显',
    ],
    limitation:
      '小屏设备(<375 宽)建议进一步下调数量;仅适用于导购型卡片,不适用于内容型 Feed。',
    citations: [
      { who: '周然的数字人', project: '内容导购频道改版', time: '今天', purpose: '确定首屏导购卡上限' },
      { who: '孙浩的数字人', project: '清凉家电会场', time: '3 周前' },
      { who: '王晨的数字人', project: 'PLUS 会员日会场', time: '1 月前' },
    ],
  },
  {
    id: 'ka-balance',
    title: '大促会场首屏氛围与效率平衡',
    conclusion: '氛围内容需要控制首屏占用,确保核心入口保持可见和可达。',
    type: 'project_experience',
    scope: '大促会场首屏',
    sourceProject: '2025 年 618 家电会场复盘',
    contributor: '李明',
    verified: '已通过项目复盘并由贡献者确认',
    visibility: 'team',
    visibilityDetail: '家电设计组',
    citedBy: 1,
    updated: '2 月前',
    problem:
      '大促氛围元素(沉浸式头图、动效)容易占据首屏主要空间,将核心入口压到折叠线之下。',
    evidence: [
      '2025 618 沉浸式头图方案:首屏核心入口点击率 -11%',
      '氛围元素占比控制在 35% 以内时首屏效率更稳定',
    ],
    limitation: '仅适用于大促会场首屏,不适用于日常营销小型活动页。',
    citations: [],
  },
]

/** 共享与引用 · 近期动态(见修改文档 §10.4) */
export interface ShareEvent {
  id: string
  type: UsageEventType
  knowledgeId: string
  knowledgeTitle: string
  actor: string
  actorRole?: string
  project: string
  purpose?: string
  time: string
  statusLabel: string
  tone: 'mint' | 'knowledge' | 'collab' | 'remind' | 'rose'
  description: string
  /** 有新反馈或等待授权时显示的额外说明 */
  detail?: string
  primaryAction: string
  /** 该事件是否需要用户处理(等待授权 / 新反馈) */
  needsAction?: boolean
}

export const SHARE_EVENTS: ShareEvent[] = [
  // ────── 3 条重点动态(§10.4) ──────
  {
    id: 'se-reused-wangchen',
    type: 'reused',
    knowledgeId: 'ka-floor',
    knowledgeTitle: '会场楼层优先级模型',
    actor: '王晨的数字分身',
    project: 'PLUS 会员日会场',
    purpose: '确定首屏楼层优先级',
    time: '2 天前',
    statusLabel: '已授权',
    tone: 'mint',
    description: '王晨的数字分身在「PLUS 会员日会场」中引用了这条知识。',
    primaryAction: '查看引用详情',
  },
  {
    id: 'se-feedback-guide',
    type: 'feedback_received',
    knowledgeId: 'ka-guide',
    knowledgeTitle: '导购卡片首屏承载数量',
    actor: '周然的数字人',
    project: '内容导购频道改版',
    time: '今天',
    statusLabel: '有新反馈',
    tone: 'knowledge',
    description: '在「内容导购频道改版」中应用后,补充了"小屏设备建议减少至 4 个"的新反馈。',
    detail: '新反馈不能自动覆盖原知识,需要经过原贡献者或知识负责人确认后再决定是否更新。',
    primaryAction: '查看反馈',
    needsAction: true,
  },
  {
    id: 'se-request-liming',
    type: 'reuse_requested',
    knowledgeId: 'ka-tag',
    knowledgeTitle: '活动标签信息层级规范',
    actor: '李明的数字人',
    project: '暑期家电会场',
    time: '1 天前',
    statusLabel: '等待授权',
    tone: 'remind',
    description: '李明的数字人希望在「暑期家电会场」中引用这条仅自己可见的知识。',
    detail: '该知识当前权限为"仅自己",授权后仅在本次项目中引用,不自动扩大共享范围。',
    primaryAction: '允许本次引用',
    needsAction: true,
  },
  // ────── 6 条历史动态,凑齐 §7"共享与引用 9" ──────
  {
    id: 'se-share-floor',
    type: 'shared',
    knowledgeId: 'ka-floor',
    knowledgeTitle: '会场楼层优先级模型',
    actor: '你',
    project: '2024 超级品类日复盘',
    time: '1 月前',
    statusLabel: '已共享',
    tone: 'collab',
    description: '你将「会场楼层优先级模型」共享给了家电设计组。',
    primaryAction: '查看共享设置',
  },
  {
    id: 'se-share-guide',
    type: 'shared',
    knowledgeId: 'ka-guide',
    knowledgeTitle: '导购卡片首屏承载数量',
    actor: '你',
    project: '导购场景优化复盘',
    time: '2 周前',
    statusLabel: '已共享',
    tone: 'collab',
    description: '你将「导购卡片首屏承载数量」共享给了家电设计组。',
    primaryAction: '查看共享设置',
  },
  {
    id: 'se-reused-zhou',
    type: 'reused',
    knowledgeId: 'ka-floor',
    knowledgeTitle: '会场楼层优先级模型',
    actor: '周然的数字人',
    project: '清凉家电会场',
    purpose: '首屏楼层策略参考',
    time: '3 周前',
    statusLabel: '已授权',
    tone: 'mint',
    description: '周然的数字人在「清凉家电会场」中引用了这条知识。',
    primaryAction: '查看引用详情',
  },
  {
    id: 'se-reused-zhao',
    type: 'reused',
    knowledgeId: 'ka-guide',
    knowledgeTitle: '导购卡片首屏承载数量',
    actor: '赵敏的数字人',
    project: '小家电专场',
    purpose: '首屏导购卡上限设置',
    time: '2 周前',
    statusLabel: '已授权',
    tone: 'mint',
    description: '赵敏的数字人在「小家电专场」中引用了这条知识。',
    primaryAction: '查看引用详情',
  },
  {
    id: 'se-reused-sun',
    type: 'reused',
    knowledgeId: 'ka-floor',
    knowledgeTitle: '会场楼层优先级模型',
    actor: '孙浩的数字人',
    project: '清凉家电会场',
    time: '3 周前',
    statusLabel: '已授权',
    tone: 'mint',
    description: '孙浩的数字人在「清凉家电会场」中引用了这条知识。',
    primaryAction: '查看引用详情',
  },
  {
    id: 'se-reused-liming-2024',
    type: 'reused',
    knowledgeId: 'ka-floor',
    knowledgeTitle: '会场楼层优先级模型',
    actor: '李明的数字人',
    project: '2024 家电超级品类日复盘',
    time: '1 月前',
    statusLabel: '已授权',
    tone: 'mint',
    description: '李明的数字人在「2024 家电超级品类日复盘」中引用了这条知识。',
    primaryAction: '查看引用详情',
  },
]

/* ============ 工作洞察 ============ */

/**
 * 复盘 / 知识候选状态机（预留类型）
 * 本轮「我的知识」不改 UI，但知识候选流转的状态类型在此统一定义，供后续页面联动复用。
 * 理想流转：建议复盘 → 复盘中 → 待补充结果 → 已形成知识候选 → 我的知识·待我确认。
 */
export type ReviewStatus =
  | 'suggested' // 建议复盘
  | 'in_progress' // 复盘中
  | 'missing_evidence' // 待补充结果
  | 'candidate_ready' // 已形成知识候选
  | 'completed' // 复盘完成

export type KnowledgeCandidateStatus = 'none' | 'draft' | 'pending_confirmation' | 'confirmed'

export type InsightPeriod = 'lastWeek' | 'last30Days' | 'month'

/* 近期工作概览：只描述正在发生的工作，不将其提前定义为洞察。 */
export const INSIGHT_OVERVIEW: Record<InsightPeriod, { summary: string; meta: string }> = {
  lastWeek: {
    summary:
      '当前正在推进「2026 年 618 家电会场首页改版」，进行历史项目检索、团队经验调用和首屏方案判断，相关结论仍在持续验证中。',
    meta: '3 个相似项目 · 2 条团队经验 · 2 位数字员工参与 · 1 份设计 Brief',
  },
  last30Days: {
    summary:
      '近 30 天持续推进「2026 年 618 家电会场首页改版」等工作，数字员工仍在汇总项目记录、协作结果和后续反馈。',
    meta: '4 个推进中任务 · 8 次数字员工协作 · 3 份工作产物',
  },
  month: {
    summary:
      '本月持续推进「2026 年 618 家电会场首页改版」，同时有 1 个已结束历史项目进入复盘建议阶段。',
    meta: '4 个推进中任务 · 1 个历史项目建议复盘 · 1 项流程问题持续观察',
  },
}

/* 模块二：当前项目洞察（618 仍处于项目准备阶段，只产出项目建议与待验证判断，不产出知识） */
export const CURRENT_PROJECT_INSIGHT = {
  name: '2026 年 618 家电会场首页改版',
  stage: '项目准备阶段',
  progress: [
    '找到 3 个相似历史项目',
    '引用了 2 条团队历史经验',
    '获得 2 位同事数字分身的补充',
    '已生成首页设计 Brief',
    '当前建议优先保证首屏核心入口效率',
  ],
  problem: {
    title: '入口数据口径确认耗时偏高',
    desc: '本周 2 次相关协作中，有 1 次用于反复确认入口点击口径，影响 Brief 定稿速度。',
  },
  // Skill 作为问题的轻量解决建议内嵌展示，不再单独占用一个大模块
  skill: {
    name: '项目启动 Brief Skill',
    desc: '可以在后续项目启动时自动完成历史项目检索、数据口径检查和标准 Brief 生成。',
  },
  // 待验证判断：可以展示，但明确不作为知识候选
  pendingValidation:
    '「首屏优先效率型结构」目前是待验证判断，需要在 618 项目上线后结合真实点击数据验证，暂不作为知识候选。',
}

/* 模块三：值得复盘的历史项目（已完成 · 建议复盘，本页与「我的知识」连接的核心模块） */
export const REVIEW_PROJECT = {
  name: '消息活动日历改版',
  status: '已完成 · 建议复盘',
  judgment:
    '该项目包含明确的问题诊断、模块 CTR、设计调整和项目决策记录，可能形成可复用的页面资源分配经验。',
  materials: [
    { label: '消息卡片 CTR', value: '10.53%' },
    { label: '活动日历 CTR', value: '0.50%' },
    { label: 'Feeds 大包裹 CTR', value: '2.01%' },
    { label: '改版设计方案', value: '已归档' },
    { label: '项目决策记录', value: '已归档' },
  ],
  missing: ['改版后的实际效果', '产品或业务反馈', '最终上线范围', '是否存在未达到预期的部分'],
  // 只展示可能的知识方向，不直接生成知识
  directions: [
    '页面资源如何根据用户使用价值分配',
    '低频但必要模块如何保留基础可达性',
    '模块 CTR、首屏占用与展示权重如何共同用于决策',
  ],
  candidateHint: '完成复盘并经过负责人确认后，符合条件的结论可以形成新的知识候选。',
}

/* 项目复盘四步内容（均为演示 Mock；上线结果类材料默认缺失，需用户补充后才能生成知识候选） */
export const REVIEW_FLOW = {
  // 步骤一：确认项目背景
  background: [
    { label: '项目目标', value: '优化消息页资源分配，让高频、高价值模块获得更合理的曝光与首屏可达性。' },
    {
      label: '原始问题',
      value: '活动日历模块占据消息页显著位置，但点击率仅 0.50%，挤压了高频消息卡片与 Feeds 的展示效率。',
    },
    { label: '参与人员', value: '林知夏（体验设计）、消息业务产品、前端开发' },
    { label: '项目时间', value: '2024 年 Q3' },
    { label: '最终上线方案', value: '活动日历收起为二级入口，消息卡片与 Feeds 大包裹前置到首屏可视区。' },
  ],
  // 步骤二：检查已有证据（上线结果、业务反馈默认缺失）
  evidence: [
    { label: '原始 CTR 数据', ready: true, note: '消息卡片 10.53% / 活动日历 0.50% / Feeds 2.01%' },
    { label: '改版方案', ready: true, note: '已归档设计稿' },
    { label: '设计决策', ready: true, note: '项目决策记录完整' },
    { label: '上线结果', ready: false, note: '缺少改版后的实际效果数据' },
    { label: '业务反馈', ready: false, note: '缺少产品或业务侧反馈' },
  ],
  // 步骤三：补充缺失结果
  missingHint: '当前材料不足以形成经过验证的知识，请补充项目实际结果。',
  resultPlaceholder:
    '例如：改版上线后活动日历入口点击占比、消息卡片与 Feeds 的点击变化、业务侧对本次改版的评价……',
  // 步骤四：生成知识候选（仅材料完整后可执行）
  candidateReadyHint: '已形成 1 条知识候选，等待你在「我的知识」中确认。',
  candidateTitle: '页面资源应按用户使用价值分配曝光与首屏位置',
}

/* 模块四：重复出现的工作问题（权重低于历史项目复盘机会，不使用大面积警告底色） */
export const RECURRING_PROBLEM = {
  title: '数据口径确认在多个项目中重复发生',
  desc: '最近 3 个项目都出现了入口或模块数据口径重复确认，导致项目启动和分析阶段增加额外沟通成本。',
  basis: [
    '2026 年 618 家电会场：首页入口点击口径重复确认',
    '2024 年家电超级品类日：楼层转化数据统计口径确认',
    '导购卡首屏数量测试：曝光与点击数据口径确认',
  ],
  improve:
    '将数据口径检查加入项目启动 Brief Skill，在项目启动时提前确认指标定义、时间范围和数据来源。',
}

/* ============ 协作网络 ============ */
export const COLLAB_OVERVIEW = {
  receivedSupport: 6,
}

export interface HelpRequest {
  id: string
  from: string
  applicant: string
  project: string
  knowledge: string
  purpose: string
  authorization: string
  risk: string
  knowledgeMeta: {
    verified: string
    permission: string
    contributor: string
    lastVerified: string
  }
}

export const HELP_REQUESTS: HelpRequest[] = [
  {
    id: 'req-wangchen',
    from: '王晨的数字分身',
    applicant: '王晨',
    project: '家电暑期会场改版',
    knowledge: '会场楼层优先级模型',
    purpose: '参考历史会场经验，确定暑期会场的首屏楼层与重点入口顺序。',
    authorization: '仅允许在「家电暑期会场改版」项目中引用，不自动扩大知识共享范围。',
    risk: '两个项目的品类结构不同，历史结论可以作为参考，但仍需结合暑期会场数据重新判断。',
    knowledgeMeta: {
      verified: '已通过项目复盘',
      permission: '家电设计组',
      contributor: '林知夏（本人）',
      lastVerified: '2025-07',
    },
  },
  {
    id: 'req-zhaomin',
    from: '赵敏的数字分身',
    applicant: '赵敏',
    project: '小家电专场页',
    knowledge: '导购卡片首屏承载数量',
    purpose: '确定小家电专场首屏一屏内导购卡片的合理数量上限。',
    authorization: '仅允许在「小家电专场页」项目中引用，不自动扩大知识共享范围。',
    risk: '小家电品类决策链更短，历史上限可以放宽，仍建议结合本次专场品类验证。',
    knowledgeMeta: {
      verified: '已通过项目复盘',
      permission: '家电设计组',
      contributor: '林知夏（本人）',
      lastVerified: '2025-06',
    },
  },
  {
    id: 'req-sunhao',
    from: '孙浩的数字分身',
    applicant: '孙浩',
    project: '清凉家电会场',
    knowledge: '活动标签信息层级规范',
    purpose: '复用标签信息层级规范，降低会场标签的扫读成本。',
    authorization: '仅允许在「清凉家电会场」项目中引用，不自动扩大知识共享范围。',
    risk: '暑期活动标签数量偏多，套用规范时需要一并启用折叠策略。',
    knowledgeMeta: {
      verified: '已通过项目复盘',
      permission: '家电设计组',
      contributor: '林知夏（本人）',
      lastVerified: '2025-05',
    },
  },
]

/* 我的协作：查找 618 家电会场历史经验（数字分身与调用能力分离） */
export interface CollabActor {
  name: string
  role: string
  tone: 'mint' | 'knowledge' | 'collab' | 'remind'
}
export const MY_COLLAB = {
  title: '查找 618 家电会场历史经验',
  resultSummary:
    '林知夏的数字员工发起任务，李明和王晨的数字员工补充历史经验与数据依据，最终形成 618 家电会场首页设计 Brief。',
  peers: [
    { name: '林知夏的数字人', role: '发起任务', tone: 'mint' },
    { name: '李明的数字人', role: '提供 2025 年会场复盘', tone: 'knowledge' },
    { name: '王晨的数字人', role: '补充入口数据与项目判断', tone: 'collab' },
  ] as CollabActor[],
  capabilities: [
    { name: '数据查询 Skill', role: '补充近 90 天数据', tone: 'knowledge' },
    { name: '风险提醒能力', role: '发现数据时间范围差异', tone: 'remind' },
  ] as CollabActor[],
  results: ['获得 2 个历史项目', '补充 1 条近期数据', '发现 1 项数据口径风险', '生成 2026 年项目 Brief'],
}

/* 协作时间线（技术词 → 用户语言） */
export interface TimelineNode {
  id: string
  who: string
  action: string // 用户语言
  rawType: string // 技术词，仅在详情次级展示
  detail: string
  tone: 'mint' | 'knowledge' | 'collab' | 'remind' | 'rose'
}
export const COLLAB_TIMELINE: TimelineNode[] = [
  {
    id: 'tl-1',
    who: '林知夏的数字人',
    action: '发起求助',
    rawType: 'request',
    detail: '发起 618 家电会场历史经验查询。',
    tone: 'mint',
  },
  {
    id: 'tl-2',
    who: '李明的数字人',
    action: '补充经验',
    rawType: 'evidence',
    detail: '补充 2025 年项目复盘：沉浸式头图降低首屏入口可见性。',
    tone: 'knowledge',
  },
  {
    id: 'tl-3',
    who: '王晨的数字人',
    action: '补充数据',
    rawType: 'data',
    detail: '补充首屏入口点击数据，量化了入口点击的下降幅度。',
    tone: 'collab',
  },
  {
    id: 'tl-4',
    who: '林知夏的数字员工',
    action: '综合结果',
    rawType: 'synthesis',
    detail: '综合历史经验与近期数据，识别数据口径风险，并形成效率型首屏结构建议。',
    tone: 'remind',
  },
  {
    id: 'tl-5',
    who: '林知夏的数字员工',
    action: '生成 Brief',
    rawType: 'brief',
    detail: '生成 2026 年 618 家电会场首页设计 Brief，并记录全部知识与协作来源。',
    tone: 'mint',
  },
]

/* 我的协作列表（合并 发起 / 参与 / 进行中 / 已完成） */
export interface MyCollaboration {
  id: string
  title: string
  role: '发起' | '参与'
  status: 'ongoing' | 'done'
  counterpart: string
  note: string
  time: string
  featured?: boolean
}
export const MY_COLLABORATIONS: MyCollaboration[] = [
  {
    id: 'mc-618',
    title: '查找 618 家电会场历史经验',
    role: '发起',
    status: 'done',
    counterpart: '3 个数字分身 + 2 项能力',
    note: '已生成 2026 年 618 家电会场首页设计 Brief',
    time: '今天',
    featured: true,
  },
  {
    id: 'mc-entry',
    title: '确认 2026 首屏重点商品入口方案',
    role: '发起',
    status: 'ongoing',
    counterpart: '王晨的数字人',
    note: '等待暑期主推品类清单',
    time: '进行中',
  },
  {
    id: 'mc-caliber',
    title: '首屏入口点击口径二次确认',
    role: '参与',
    status: 'ongoing',
    counterpart: '数据查询 Skill',
    note: '数据口径对齐中',
    time: '进行中',
  },
  {
    id: 'mc-c1',
    title: '首屏入口点击口径对齐',
    role: '参与',
    status: 'done',
    counterpart: '王晨的数字人',
    note: '统一近 90 天口径',
    time: '2 天前',
  },
  {
    id: 'mc-c2',
    title: '2025 会场复盘要点补充',
    role: '发起',
    status: 'done',
    counterpart: '李明的数字人',
    note: '补充 3 条复盘结论',
    time: '3 天前',
  },
  {
    id: 'mc-c3',
    title: '标签层级规范复用',
    role: '参与',
    status: 'done',
    counterpart: '周然的数字人',
    note: '应用于 PLUS 会员日',
    time: '5 天前',
  },
  {
    id: 'mc-c4',
    title: '导购卡数量建议',
    role: '发起',
    status: 'done',
    counterpart: '赵敏的数字人',
    note: '确定首屏 4–6 个',
    time: '1 周前',
  },
]

export interface RecommendedPeer {
  id: string
  name: string
  domain: string
  reason: string
  offers: string[]
  recentProject: string
  tone: 'knowledge' | 'collab' | 'remind'
}
export const RECOMMENDED_PEERS: RecommendedPeer[] = [
  {
    id: 'peer-liming',
    name: '李明的数字人',
    domain: '营销会场、数据复盘',
    reason: '参与过 2025 年 618 家电会场复盘，与当前项目相似度 92%。',
    offers: ['会场复盘经验', '首屏入口数据', '历史项目决策依据'],
    recentProject: '2025 618 家电会场复盘',
    tone: 'knowledge',
  },
  {
    id: 'peer-wangchen',
    name: '王晨的数字人',
    domain: '首页体验、活动入口',
    reason: '正在负责家电暑期会场改版，首屏入口判断经验可直接迁移。',
    offers: ['首屏入口数据', '楼层优先级判断', '暑期品类结构'],
    recentProject: '家电暑期会场改版',
    tone: 'collab',
  },
  {
    id: 'peer-zhouran',
    name: '周然的数字人',
    domain: '导购场景、内容策略',
    reason: '在 PLUS 会员日沉淀过导购卡承载经验，补齐当前缺的导购视角。',
    offers: ['导购卡经验', '标签层级规范', '内容策略参考'],
    recentProject: 'PLUS 会员日活动页',
    tone: 'remind',
  },
]

/* ============ 数字人管理：能力与 Skill ============ */
export type SkillStatus = 'enabled' | 'disabled'
export type SkillSource = '团队共享' | '个人配置' | '平台内置'
export interface ConfiguredSkill {
  id: string
  name: string
  desc: string
  /** 用途：数字人用它来做什么 */
  purpose: string
  /** 来源：团队共享 / 个人配置 / 平台内置 */
  source: SkillSource
  status: SkillStatus
  /** 最近一次调用时间 */
  lastUsed: string
}
export const CONFIGURED_SKILLS: ConfiguredSkill[] = [
  {
    id: 'sk-data',
    name: '数据查询 Skill',
    desc: '按场景取回首页 / 会场入口的点击与转化数据。',
    purpose: '为会场决策取回入口点击与转化数据',
    source: '团队共享',
    status: 'enabled',
    lastUsed: '今天 14:20',
  },
  {
    id: 'sk-history',
    name: '历史项目检索 Skill',
    desc: '在团队 Wiki 与项目库中检索相似会场案例。',
    purpose: '检索相似历史会场，复用过往结构与结论',
    source: '团队共享',
    status: 'enabled',
    lastUsed: '今天 11:38',
  },
  {
    id: 'sk-review',
    name: '复盘要点提炼 Skill',
    desc: '从项目复盘文档中提取关键结论与风险。',
    purpose: '从复盘文档中提炼可沉淀的结论与风险',
    source: '个人配置',
    status: 'enabled',
    lastUsed: '昨天',
  },
  {
    id: 'sk-audit',
    name: '设计走查 Skill',
    desc: '按信息层级与对比度规范检查页面稿件。',
    purpose: '按规范走查稿件的信息层级与对比度',
    source: '平台内置',
    status: 'enabled',
    lastUsed: '本周一',
  },
  {
    id: 'sk-floor',
    name: '会场楼层结构 Skill',
    desc: '根据品类与转化目标推荐楼层顺序。',
    purpose: '根据品类与转化目标推荐楼层顺序',
    source: '团队共享',
    status: 'disabled',
    lastUsed: '上周',
  },
  {
    id: 'sk-tag',
    name: '标签规范校验 Skill',
    desc: '校验活动标签的信息层级与数量。',
    purpose: '校验活动标签的层级与数量是否合规',
    source: '个人配置',
    status: 'enabled',
    lastUsed: '上周',
  },
]

/* ============ 数字人管理：活动记录 ============
 * 5 类活动：Skill 调用 / 数字人协作 / Brief 生成 / 知识候选提交 / 用户确认操作。
 * 供活动记录分区做分类筛选与时间流展示。
 */
export type ActivityCategory =
  | 'skill_call'
  | 'agent_collab'
  | 'brief_generation'
  | 'knowledge_submit'
  | 'user_confirm'

export const ACTIVITY_CATEGORY_LABELS: Record<ActivityCategory, string> = {
  skill_call: 'Skill 调用',
  agent_collab: '数字人协作',
  brief_generation: 'Brief 生成',
  knowledge_submit: '知识候选提交',
  user_confirm: '用户确认操作',
}

export interface ActivityEntry {
  id: string
  category: ActivityCategory
  title: string
  detail?: string
  actor: string
  time: string
  tone: 'mint' | 'knowledge' | 'collab' | 'remind' | 'rose'
}

export const ACTIVITY_LOG: ActivityEntry[] = [
  {
    id: 'act-1',
    category: 'brief_generation',
    title: '生成 2026 年 618 家电会场首页设计 Brief',
    detail: '整合近 90 天首屏入口数据与 2 个历史会场结构',
    actor: '林知夏的数字人',
    time: '今天 15:02',
    tone: 'mint',
  },
  {
    id: 'act-2',
    category: 'skill_call',
    title: '调用「数据查询 Skill」取回近 90 天首屏入口点击',
    detail: 'scene=home · range=90d',
    actor: '数据查询 Skill',
    time: '今天 14:20',
    tone: 'knowledge',
  },
  {
    id: 'act-3',
    category: 'agent_collab',
    title: '请求王晨、李明的数字人补充历史会场依据',
    detail: '获得 2 条首屏入口判断经验',
    actor: '林知夏的数字人',
    time: '今天 11:38',
    tone: 'collab',
  },
  {
    id: 'act-4',
    category: 'knowledge_submit',
    title: '提交「页面空间按使用价值分配」知识候选待确认',
    actor: '林知夏的数字人',
    time: '昨天',
    tone: 'remind',
  },
  {
    id: 'act-5',
    category: 'user_confirm',
    title: '你确认了「首屏优先效率型结构」方向',
    actor: '林知夏',
    time: '昨天',
    tone: 'mint',
  },
]
