import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  KNOWLEDGE_ASSETS,
  KNOWLEDGE_TYPE_LABELS,
  NEW_KNOWLEDGE,
  SHARE_EVENTS,
  type KnowledgeAsset,
  type KnowledgeType,
  type ShareEvent,
  type Visibility,
} from '../data/mockData'

export type ShareScope = 'self' | 'project' | 'group' | 'more'

export const SCOPE_LABELS: Record<ShareScope, string> = {
  self: '仅自己',
  project: '当前项目',
  group: '家电设计组',
  more: '更多团队',
}

export type UnderstandingStatus = 'pending' | 'confirmed' | 'modified' | 'ignored'

export interface ImpactItem {
  id: string
  text: string
  time: string
  highlight?: boolean
}

interface Toast {
  id: number
  message: string
  tone: 'success' | 'info'
}

/**
 * 「我的知识」候选沉淀 payload。
 * 与修改文档 §9.6 三步确认保持一致:
 *   步骤 1: 确认内容(可能修改的标题 / 结论 / 适用范围 / 限制条件)
 *   步骤 2: 设置知识类型
 *   步骤 3: 设置使用权限
 */
export interface ConfirmCandidatePayload {
  title: string
  conclusion: string
  scope: string
  limitation: string
  type: KnowledgeType
  visibility: Visibility
  /** team 时的团队名(默认"家电设计组") */
  visibilityDetail?: string
}

interface DemoState {
  /* ─── ERP 登录 ─── */
  authenticated: boolean

  /* ─── 首屏核心入口 / 王晨授权保留 ─── */
  knowledgeShared: boolean
  shareScope: ShareScope
  sharedCount: number
  pendingCount: number
  reusedCount: number
  peopleHelped: number
  monthlyCitations: number
  wangchenAuthorized: boolean
  impactFeed: ImpactItem[]
  understandings: Record<string, UnderstandingStatus>
  toasts: Toast[]

  /* ─── 我的知识 · 新状态 ─── */
  /** 已确认的知识资产(可见列表)。候选沉淀后新条目插入首位。 */
  assets: KnowledgeAsset[]
  /** 页面顶部 Tab 显示的资产总数(24 → 25)。真实业务下应等于 assets.length,demo 中为固定基数 + 增量。 */
  assetCount: number
  /** 共享与引用动态,可能追加"你共享了新知识"事件。 */
  shareEvents: ShareEvent[]
  /** 顶部 Tab 显示的共享与引用动态数量(9)。 */
  shareEventCount: number
  /** 已允许 / 已拒绝的动态 ids,用于视觉反馈。 */
  authorizedEventIds: Set<string>
  declinedEventIds: Set<string>
  feedbackHandledIds: Set<string>
}

interface DemoActions {
  /* 保留 */
  authorizeWangchen: () => void
  setUnderstanding: (id: string, status: UnderstandingStatus) => void
  showToast: (message: string, tone?: Toast['tone']) => void
  dismissToast: (id: number) => void
  /* 新增 */
  confirmCandidate: (payload: ConfirmCandidatePayload) => void
  authorizeShareEvent: (id: string) => void
  declineShareEvent: (id: string) => void
  markFeedbackHandled: (id: string) => void
  /* ERP 登录 */
  login: () => void
  logout: () => void
}

type DemoContextValue = DemoState & DemoActions

const DemoContext = createContext<DemoContextValue | null>(null)

const INITIAL_IMPACT: ImpactItem[] = [
  {
    id: 'imp-tag',
    text: '你的「活动标签信息层级规范」本周支持了 4 位同事。',
    time: '本周',
    highlight: true,
  },
  {
    id: 'imp-floor',
    text: '你的「会场楼层优先级模型」被用于 2024 家电超级品类日复盘。',
    time: '上周',
  },
]

/** 基础知识资产数量(修改文档 §7:知识资产 24)。真实资产会以 KNOWLEDGE_ASSETS 展示,其余以数字体现。 */
const BASE_ASSET_COUNT = 24

let toastSeq = 1

export function DemoProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false)

  const [knowledgeShared, setKnowledgeShared] = useState(false)
  const [shareScope, setShareScope] = useState<ShareScope>('group')
  const [sharedCount, setSharedCount] = useState(12)
  const [reusedCount, setReusedCount] = useState(9)
  const [peopleHelped, setPeopleHelped] = useState(9)
  const [monthlyCitations, setMonthlyCitations] = useState(18)
  const [wangchenAuthorized, setWangchenAuthorized] = useState(false)
  const [impactFeed, setImpactFeed] = useState<ImpactItem[]>(INITIAL_IMPACT)
  const [understandings, setUnderstandings] = useState<Record<string, UnderstandingStatus>>({
    'u-1': 'pending',
    'u-2': 'pending',
    'u-3': 'pending',
  })
  const [toasts, setToasts] = useState<Toast[]>([])

  const [assets, setAssets] = useState<KnowledgeAsset[]>(KNOWLEDGE_ASSETS)
  const [assetCount, setAssetCount] = useState(BASE_ASSET_COUNT)
  const [shareEvents, setShareEvents] = useState<ShareEvent[]>(SHARE_EVENTS)
  const [authorizedEventIds, setAuthorizedEventIds] = useState<Set<string>>(new Set())
  const [declinedEventIds, setDeclinedEventIds] = useState<Set<string>>(new Set())
  const [feedbackHandledIds, setFeedbackHandledIds] = useState<Set<string>>(new Set())

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback(
    (message: string, tone: Toast['tone'] = 'success') => {
      const id = toastSeq++
      setToasts((prev) => [...prev, { id, message, tone }])
      window.setTimeout(() => dismissToast(id), 3200)
    },
    [dismissToast],
  )

  /**
   * 候选 → 知识资产。执行"确认并沉淀":
   *   1) 待我确认 1 → 0(knowledgeShared = true 使 pendingCount 归 0)
   *   2) 知识资产 24 → 25(assetCount + 1),新知识插入 assets 首位
   *   3) 权限为 team 时,追加一条"你共享了新知识"动态
   *   4) impactFeed 追加一条动态
   *   5) 轻量成功提示(修改文档 §9.7)
   */
  const confirmCandidate = useCallback(
    (payload: ConfirmCandidatePayload) => {
      if (knowledgeShared) return

      const newAsset: KnowledgeAsset = {
        id: NEW_KNOWLEDGE.id,
        title: payload.title,
        conclusion: payload.conclusion,
        type: payload.type,
        scope: payload.scope,
        sourceProject: NEW_KNOWLEDGE.sourceProject,
        contributor: NEW_KNOWLEDGE.contributor,
        verified: '已通过项目复盘',
        visibility: payload.visibility,
        visibilityDetail: payload.visibility === 'team' ? payload.visibilityDetail ?? '家电设计组' : undefined,
        citedBy: 0,
        updated: '刚刚',
        problem: NEW_KNOWLEDGE.problem,
        evidence: NEW_KNOWLEDGE.rawData.map((d) => `${d.label}:${d.value}`),
        limitation: payload.limitation,
        citations: [],
        justConfirmed: true,
      }

      setAssets((prev) => [newAsset, ...prev.filter((a) => a.id !== newAsset.id)])
      setAssetCount((c) => c + 1)
      setKnowledgeShared(true)

      // 权限→ShareScope 映射(供 impactFeed 复用)
      const scope: ShareScope =
        payload.visibility === 'private'
          ? 'self'
          : payload.visibility === 'project'
            ? 'project'
            : payload.visibility === 'team'
              ? 'group'
              : 'more'
      setShareScope(scope)

      // 团队 / 项目 权限则追加一条共享动态,顶部 Tab"共享与引用"数量 +1
      if (payload.visibility !== 'private') {
        const teamName = payload.visibility === 'team' ? payload.visibilityDetail ?? '家电设计组' : '当前项目'
        setShareEvents((prev) => [
          {
            id: `se-just-shared-${newAsset.id}`,
            type: 'shared',
            knowledgeId: newAsset.id,
            knowledgeTitle: newAsset.title,
            actor: '你',
            project: NEW_KNOWLEDGE.sourceProject,
            time: '刚刚',
            statusLabel: '刚刚共享',
            tone: 'mint',
            description: `你将「${newAsset.title}」共享给了${teamName}。`,
            primaryAction: '查看共享设置',
          } satisfies ShareEvent,
          ...prev,
        ])
        setSharedCount((c) => (c < 13 ? 13 : c))
      }

      setImpactFeed((prev) => {
        if (prev.some((i) => i.id === 'imp-cand-confirmed')) return prev
        return [
          {
            id: 'imp-cand-confirmed',
            text: `你确认的「${newAsset.title}」已沉淀,可供${
              payload.visibility === 'private'
                ? '你的数字人使用'
                : `${payload.visibility === 'team' ? payload.visibilityDetail ?? '家电设计组' : '当前项目'}的数字人引用`
            }。`,
            time: '刚刚',
            highlight: true,
          },
          ...prev,
        ]
      })

      showToast('已沉淀为知识资产,并按照你的权限设置提供给数字人使用')
    },
    [knowledgeShared, showToast],
  )

  const authorizeWangchen = useCallback(() => {
    setWangchenAuthorized(true)
    setReusedCount((c) => c + 1)
    setPeopleHelped((c) => c + 1)
    setMonthlyCitations((c) => c + 1)
    setImpactFeed((prev) => {
      if (prev.some((i) => i.id === 'imp-wangchen')) return prev
      return [
        {
          id: 'imp-wangchen',
          text: '王晨的数字人已引用你的「会场楼层优先级模型」,用于家电暑期会场改版。',
          time: '刚刚',
          highlight: true,
        },
        ...prev,
      ]
    })
    showToast('你的数字人已将经验提供给王晨,并保留来源与适用范围')
  }, [showToast])

  const setUnderstanding = useCallback(
    (id: string, status: UnderstandingStatus) => {
      setUnderstandings((prev) => ({ ...prev, [id]: status }))
      if (status === 'confirmed') showToast('已更新数字人对你的工作理解')
      if (status === 'ignored') showToast('已忽略这条理解', 'info')
    },
    [showToast],
  )

  /* 共享与引用动态 · 操作 */
  const authorizeShareEvent = useCallback(
    (id: string) => {
      const event = shareEvents.find((e) => e.id === id)
      if (!event) return
      setAuthorizedEventIds((prev) => {
        const next = new Set(prev)
        next.add(id)
        return next
      })
      // 允许后动态状态调整为"已授权"(视觉侧读取 authorizedEventIds 覆盖 statusLabel)
      showToast(`已允许本次引用,${event.actor}的数字人可在「${event.project}」中使用该知识`)
    },
    [shareEvents, showToast],
  )

  const declineShareEvent = useCallback(
    (id: string) => {
      setDeclinedEventIds((prev) => {
        const next = new Set(prev)
        next.add(id)
        return next
      })
      showToast('已拒绝本次引用,原知识权限不变', 'info')
    },
    [showToast],
  )

  const markFeedbackHandled = useCallback(
    (id: string) => {
      setFeedbackHandledIds((prev) => {
        const next = new Set(prev)
        next.add(id)
        return next
      })
      showToast('已查看反馈,新反馈不会自动改写原知识,需你确认后再决定是否更新', 'info')
    },
    [showToast],
  )

  const shareEventCount = useMemo(() => shareEvents.length, [shareEvents])
  const pendingCount = knowledgeShared ? 0 : 1

  /* ─── ERP 统一身份 + Demo 身份预览 ─── */
  const login = useCallback(() => {
    setAuthenticated(true)
  }, [])

  /** 退出登录只清空登录态，不清空业务演示数据。 */
  const logout = useCallback(() => {
    setAuthenticated(false)
  }, [])

  const value = useMemo<DemoContextValue>(
    () => ({
      authenticated,
      knowledgeShared,
      shareScope,
      sharedCount,
      pendingCount,
      reusedCount,
      peopleHelped,
      monthlyCitations,
      wangchenAuthorized,
      impactFeed,
      understandings,
      toasts,
      assets,
      assetCount,
      shareEvents,
      shareEventCount,
      authorizedEventIds,
      declinedEventIds,
      feedbackHandledIds,
      confirmCandidate,
      authorizeWangchen,
      authorizeShareEvent,
      declineShareEvent,
      markFeedbackHandled,
      setUnderstanding,
      showToast,
      dismissToast,
      login,
      logout,
    }),
    [
      authenticated,
      knowledgeShared,
      shareScope,
      sharedCount,
      pendingCount,
      reusedCount,
      peopleHelped,
      monthlyCitations,
      wangchenAuthorized,
      impactFeed,
      understandings,
      toasts,
      assets,
      assetCount,
      shareEvents,
      shareEventCount,
      authorizedEventIds,
      declinedEventIds,
      feedbackHandledIds,
      confirmCandidate,
      authorizeWangchen,
      authorizeShareEvent,
      declineShareEvent,
      markFeedbackHandled,
      setUnderstanding,
      showToast,
      dismissToast,
      login,
      logout,
    ],
  )

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useDemo() {
  const ctx = useContext(DemoContext)
  if (!ctx) throw new Error('useDemo 必须在 DemoProvider 内使用')
  return ctx
}

/** 视图层辅助:根据当前 event id 计算实际展示状态。 */
export function resolveShareEventStatus(
  event: ShareEvent,
  authorizedIds: Set<string>,
  declinedIds: Set<string>,
  feedbackIds: Set<string>,
) {
  if (declinedIds.has(event.id)) return { label: '已拒绝', tone: 'neutral' as const, closed: true }
  if (authorizedIds.has(event.id)) return { label: '已授权', tone: 'mint' as const, closed: true }
  if (feedbackIds.has(event.id)) return { label: '反馈已查看', tone: 'knowledge' as const, closed: true }
  return { label: event.statusLabel, tone: event.tone, closed: false }
}

// eslint-disable-next-line react-refresh/only-export-components
export { KNOWLEDGE_TYPE_LABELS }
