import { useEffect, useState } from 'react'
import {
  X,
  History,
  Lightbulb,
  BarChart3,
  UserRound,
  Workflow,
  FileText,
  ExternalLink,
  ChevronDown,
  ArrowUpRight,
  TrendingDown,
  TrendingUp,
  Sparkles,
} from 'lucide-react'
import {
  WORKSPACE_ANALYSIS,
  WORKSPACE_TECH_LOG,
  WORKSPACE_REFERENCES,
  CORE_EXPERIENCE_REF,
  BRIEF,
  type WorkspaceRef,
} from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'
import { cn } from '../../lib/cn'

export type DetailContent =
  | { kind: 'ref'; ref: WorkspaceRef }
  | { kind: 'process' }
  | { kind: 'sources' }
  | { kind: 'tools' }
  | { kind: 'collaboration' }
  | { kind: 'brief' }

type PanelTab = 'sources' | 'tools' | 'collaboration'

const KIND_META: Record<
  WorkspaceRef['kind']   | 'process' | 'sources' | 'tools' | 'collaboration' | 'brief',
  { icon: typeof History; label: string; tone: string }
> = {
  project: { icon: History, label: '历史项目', tone: 'text-knowledge' },
  experience: { icon: Lightbulb, label: '团队经验', tone: 'text-mint-300' },
  data: { icon: BarChart3, label: '数据来源', tone: 'text-remind' },
  peer: { icon: UserRound, label: '数字员工协作贡献', tone: 'text-collab' },
  process: { icon: Workflow, label: '本次工作过程', tone: 'text-mint-300' },
  sources: { icon: FileText, label: '全部资料', tone: 'text-knowledge' },
  tools: { icon: Workflow, label: '调用工具', tone: 'text-remind' },
  collaboration: { icon: UserRound, label: '数字员工协作', tone: 'text-collab' },
  brief: { icon: FileText, label: '工作产物', tone: 'text-mint-300' },
}

export function DetailPanel({
  content,
  onClose,
  onOpenSources,
  onOpenTools,
  onOpenCollaboration,
}: {
  content: DetailContent | null
  onClose: () => void
  onOpenSources: () => void
  onOpenTools: () => void
  onOpenCollaboration: () => void
}) {
  const isTaskResourcePanel =
    content?.kind === 'sources' || content?.kind === 'tools' || content?.kind === 'collaboration'
  const initialTab: PanelTab = content?.kind === 'tools'
    ? 'tools'
    : content?.kind === 'collaboration'
      ? 'collaboration'
      : 'sources'
  const [activeTab, setActiveTab] = useState<PanelTab>(initialTab)

  useEffect(() => {
    if (!isTaskResourcePanel) return
    setActiveTab(initialTab)
  }, [content?.kind, initialTab, isTaskResourcePanel])

  const switchTab = (tab: PanelTab) => {
    setActiveTab(tab)
    if (tab === 'sources') onOpenSources()
    if (tab === 'tools') onOpenTools()
    if (tab === 'collaboration') onOpenCollaboration()
  }

  const meta = content
    ? KIND_META[content.kind === 'ref' ? content.ref.kind : content.kind]
    : null
  const Icon = meta?.icon ?? FileText

  const title = isTaskResourcePanel
    ? '本次任务资料'
    : content?.kind === 'ref'
      ? content.ref.title
      : content?.kind === 'process'
        ? '本次工作过程'
        : content?.kind === 'brief'
          ? BRIEF.title
          : ''
  const chip = isTaskResourcePanel
    ? '项目资料、工具调用与数字员工协作记录'
    : content?.kind === 'ref'
      ? content.ref.chip
      : content?.kind === 'process'
        ? '任务分析'
        : content?.kind === 'brief'
          ? '数字员工生成 · 项目启动 Brief'
          : ''

  return (
    <div
      className={cn(
        'absolute right-0 top-0 z-20 flex h-full w-[440px] flex-col border-l border-white/[0.08] bg-base shadow-[-24px_0_48px_-24px_rgba(0,0,0,0.6)] transition-transform duration-300 ease-out',
        content ? 'translate-x-0' : 'pointer-events-none translate-x-full',
      )}
    >
      {/* 头部 */}
      <div className="flex items-start gap-3 border-b border-white/[0.06] px-5 py-4">
        <div className={cn('mt-0.5 rounded-[10px] bg-white/[0.05] p-2', meta?.tone)}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold leading-snug text-slate-100">{title}</div>
          {chip && <div className="mt-0.5 text-[11px] text-slate-500">{chip}</div>}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-white/[0.06] hover:text-slate-200"
          aria-label="关闭"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* 任务资料固定 Tab：切换 Tab 时同步切换下方分类内容 */}
      {isTaskResourcePanel && (
        <div className="flex border-b border-white/[0.06] px-5">
          {([
            { key: 'sources', label: '全部资料' },
            { key: 'tools', label: '调用工具' },
            { key: 'collaboration', label: '数字员工协作' },
          ] as { key: PanelTab; label: string }[]).map((tab, index) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => switchTab(tab.key)}
              className={cn(
                'border-b-2 px-1 py-2.5 text-[12px] font-medium transition-colors',
                index > 0 && 'ml-5',
                activeTab === tab.key
                  ? 'border-mint-400 text-mint-300'
                  : 'border-transparent text-slate-500 hover:text-slate-300',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* 主体（独立滚动）：任务资料按当前 Tab 渲染，详情与 Brief 保持原内容 */}
      <div className="flex-1 overflow-y-auto px-5 py-5">
        {isTaskResourcePanel && activeTab === 'sources' && <SourcesBody />}
        {isTaskResourcePanel && activeTab === 'tools' && <ToolsBody />}
        {isTaskResourcePanel && activeTab === 'collaboration' && <CollaborationBody />}
        {content?.kind === 'ref' && <RefBody refItem={content.ref} />}
        {content?.kind === 'process' && <ProcessBody />}
        {content?.kind === 'brief' && <BriefBody />}
      </div>
    </div>
  )
}

/* ---------- 通用小组件 ---------- */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="text-[13px] leading-relaxed text-slate-300">{children}</div>
    </div>
  )
}

function PanelAction({
  icon: ActionIcon,
  label,
  onClick,
}: {
  icon: typeof ExternalLink
  label: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="mt-1 flex w-full items-center justify-center gap-1.5 rounded-[10px] border border-white/[0.08] bg-surface-1 px-4 py-2.5 text-[13px] font-medium text-slate-200 transition-colors hover:border-white/[0.16] hover:bg-surface-2"
    >
      <ActionIcon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}

/* ---------- 引用详情：按 kind 分支 ---------- */

function RefBody({ refItem }: { refItem: WorkspaceRef }) {
  const { showToast } = useDemo()

  if (refItem.kind === 'project') {
    const d = refItem.detail
    return (
      <div className="space-y-5">
        <Field label="项目背景">{d.background}</Field>
        <Field label="核心问题">{d.problem}</Field>
        <Field label="设计方案">{d.solution}</Field>
        <Field label="结果数据">
          <span className="text-slate-200">{d.result}</span>
        </Field>
        <div className="rounded-[12px] border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-mint-300">
            <Sparkles className="h-3 w-3" />
            与当前任务的关联
          </div>
          <div className="text-[13px] leading-relaxed text-slate-300">{d.relation}</div>
        </div>
        <PanelAction
          icon={ExternalLink}
          label="查看原始资料"
          onClick={() => showToast('已打开原始项目资料（演示）', 'info')}
        />
      </div>
    )
  }

  if (refItem.kind === 'experience') {
    const d = refItem.detail
    return (
      <div className="space-y-5">
        <div className="rounded-[12px] border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3">
          <div className="mb-1 text-[11px] font-medium text-mint-300">经验结论</div>
          <div className="text-[13px] leading-relaxed text-slate-200">{d.conclusion}</div>
        </div>
        <Field label="来源项目">
          <div className="flex flex-wrap gap-1.5">
            {d.sourceProjects.map((p) => (
              <span
                key={p}
                className="rounded-pill bg-white/[0.05] px-2.5 py-1 text-[12px] text-slate-300"
              >
                {p}
              </span>
            ))}
          </div>
        </Field>
        <Field label="适用范围">{d.scope}</Field>
        <Field label="最近验证时间">{d.lastVerified}</Field>
        <Field label="哪些项目引用过">
          <ul className="space-y-1.5">
            {d.citedBy.map((c) => (
              <li key={c} className="flex items-center gap-2">
                <span className="h-1 w-1 rounded-full bg-mint-400/70" />
                {c}
              </li>
            ))}
          </ul>
        </Field>
      </div>
    )
  }

  if (refItem.kind === 'data') {
    const d = refItem.detail
    return (
      <div className="space-y-5">
        <Field label="数据范围">{d.range}</Field>
        <div>
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            核心指标
          </div>
          <div className="space-y-2">
            {d.metrics.map((m) => (
              <div
                key={m.label}
                className="flex items-center justify-between rounded-[10px] border border-white/[0.06] bg-surface-1 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <div className="text-[13px] text-slate-200">{m.label}</div>
                  <div className="text-[11px] text-slate-500">{m.value}</div>
                </div>
                {m.delta && (
                  <span
                    className={cn(
                      'flex shrink-0 items-center gap-1 rounded-pill px-2 py-1 text-[12px] font-semibold',
                      m.delta.startsWith('-')
                        ? 'bg-rose/10 text-rose'
                        : 'bg-mint-400/10 text-mint-300',
                    )}
                  >
                    {m.delta.startsWith('-') ? (
                      <TrendingDown className="h-3 w-3" />
                    ) : (
                      <TrendingUp className="h-3 w-3" />
                    )}
                    {m.delta}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-[12px] border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3">
          <div className="mb-1 text-[11px] font-medium text-mint-300">关键结论</div>
          <div className="text-[13px] leading-relaxed text-slate-300">{d.conclusion}</div>
        </div>
        <Field label="数据时间">{d.time}</Field>
        <Field label="口径说明">{d.caliber}</Field>
        <PanelAction
          icon={ExternalLink}
          label="查看原始数据"
          onClick={() => showToast('已打开原始数据看板（演示）', 'info')}
        />
      </div>
    )
  }

  // peer
  const d = refItem.detail
  return (
    <div className="space-y-5">
      <Field label="角色和擅长领域">{d.field}</Field>
      <Field label="引用了哪条经验">{d.citedExperience}</Field>
      <div className="rounded-[12px] border border-collab/25 bg-collab/[0.06] px-4 py-3">
        <div className="mb-1 text-[11px] font-medium text-collab">具体贡献的判断</div>
        <div className="text-[13px] leading-relaxed text-slate-200">{d.contribution}</div>
      </div>
      <Field label="知识来源">{d.knowledgeSource}</Field>
      <PanelAction
        icon={ArrowUpRight}
        label="发起进一步协作"
        onClick={() => showToast('已向该数字员工发起协作邀请（演示）', 'info')}
      />
    </div>
  )
}

/* ---------- 全部资料集合 ---------- */

function SourcesBody() {
  const projects = WORKSPACE_REFERENCES.filter((ref) => ref.kind === 'project')
  const dataSources = WORKSPACE_REFERENCES.filter((ref) => ref.kind === 'data')
  const coreExperience = CORE_EXPERIENCE_REF.kind === 'experience' ? CORE_EXPERIENCE_REF.detail : null

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-[12px] font-semibold text-slate-200">相似历史项目</h3>
          <span className="text-[11px] text-slate-500">{projects.length} 个已完成项目</span>
        </div>
        <div className="space-y-2">
          {projects.map((ref) => (
            <div key={ref.id} className="rounded-[10px] border border-white/[0.06] bg-surface-1 px-3.5 py-3">
              <div className="flex items-start gap-2">
                <History className="mt-0.5 h-4 w-4 shrink-0 text-knowledge" />
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium text-slate-200">{ref.title}</div>
                  <div className="mt-1 text-[11px] text-slate-500">{ref.chip} · 真实项目</div>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-slate-400">{ref.detail.relation}</p>
                </div>
              </div>
            </div>
          ))}
          <div className="rounded-[10px] border border-dashed border-white/[0.06] px-3.5 py-2.5 text-[12px] text-slate-500">
            另有 1 个历史会场项目参与相似度分析
          </div>
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-[12px] font-semibold text-slate-200">已确认团队经验</h3>
          <span className="text-[11px] text-mint-300">2 条已确认</span>
        </div>
        <div className="space-y-2">
          <div className="rounded-[10px] border border-mint-400/15 bg-mint-400/[0.04] px-3.5 py-3">
            <div className="flex items-center gap-2 text-[13px] font-medium text-slate-200">
              <Lightbulb className="h-4 w-4 text-mint-300" />
              {CORE_EXPERIENCE_REF.title.replace('团队经验：', '')}
            </div>
            <p className="mt-1.5 text-[12px] leading-relaxed text-slate-400">{coreExperience?.conclusion}</p>
            <div className="mt-2 text-[11px] text-slate-500">✓ 已确认经验 · {coreExperience?.lastVerified}</div>
          </div>
          <div className="rounded-[10px] border border-mint-400/15 bg-mint-400/[0.04] px-3.5 py-3">
            <div className="flex items-center gap-2 text-[13px] font-medium text-slate-200">
              <Lightbulb className="h-4 w-4 text-mint-300" />
              大促会场首屏氛围与效率平衡
            </div>
            <p className="mt-1.5 text-[12px] leading-relaxed text-slate-400">氛围内容需要控制首屏占用，确保核心入口保持可见和可达。</p>
            <div className="mt-2 text-[11px] text-slate-500">✓ 已确认经验 · 来源：2025 年 618 家电会场复盘</div>
          </div>
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-3">
          <h3 className="text-[12px] font-semibold text-slate-200">业务数据依据</h3>
          <span className="text-[11px] text-slate-500">1 组数据</span>
        </div>
        {dataSources.map((ref) => (
          <div key={ref.id} className="rounded-[10px] border border-remind/15 bg-remind/[0.04] px-3.5 py-3">
            <div className="flex items-center gap-2 text-[13px] font-medium text-slate-200">
              <BarChart3 className="h-4 w-4 text-remind" />
              {ref.title}
            </div>
            <div className="mt-1.5 text-[12px] text-slate-400">{ref.detail.range}</div>
            <div className="mt-2 text-[11px] text-slate-500">{ref.chip} · 当前用户有权访问</div>
          </div>
        ))}
      </section>

      <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] px-3.5 py-2.5 text-[11.5px] leading-relaxed text-slate-500">
        此处仅汇总任务依据资料；工具执行记录和同事数字员工贡献分别归入对应 Tab。
      </div>
    </div>
  )
}

/* ---------- 调用工具与数字员工协作 ---------- */

function ToolsBody() {
  const dataRef = WORKSPACE_REFERENCES.find((ref) => ref.kind === 'data')

  return (
    <div className="space-y-5">
      <div className="rounded-[12px] border border-knowledge/20 bg-knowledge/[0.05] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-knowledge/12 text-knowledge">
            <BarChart3 className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[13.5px] font-semibold text-slate-100">数据查询 Skill</h3>
              <span className="text-[11px] text-mint-300">已完成</span>
            </div>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-400">读取近 90 天首页营销入口点击数据，为首屏结构判断补充近期业务证据。</p>
          </div>
        </div>
        <dl className="mt-3 space-y-2 border-t border-white/[0.06] pt-3 text-[12px]">
          <ToolMeta label="输入" value="618 会场首屏入口、沉浸式头图、效率型楼层" />
          <ToolMeta label="数据范围" value={dataRef?.kind === 'data' ? dataRef.detail.time : '近 90 天'} />
          <ToolMeta label="输出" value="3 项核心指标与 1 条数据结论" />
          <ToolMeta label="权限" value="当前用户有权访问" />
        </dl>
      </div>

      <div className="rounded-[12px] border border-remind/20 bg-remind/[0.05] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-remind/12 text-remind">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[13.5px] font-semibold text-slate-100">风险提醒能力</h3>
              <span className="text-[11px] text-remind">发现 1 项风险</span>
            </div>
            <p className="mt-1 text-[12px] leading-relaxed text-slate-400">识别历史项目数据与近 90 天数据的时间范围不同，提醒统一统计口径后再做直接对比。</p>
          </div>
        </div>
        <div className="mt-3 rounded-[9px] bg-base/50 px-3 py-2.5 text-[12px] leading-relaxed text-slate-400">
          待确认：首屏曝光 UV 与入口点击 UV 的统计周期和页面范围。
        </div>
      </div>

      <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] px-3.5 py-2.5 text-[11.5px] leading-relaxed text-slate-500">
        工具仅在本次任务和当前授权范围内执行，不会扩大用户的数据访问权限。
      </div>
    </div>
  )
}

function CollaborationBody() {
  const peerRef = WORKSPACE_REFERENCES.find((ref) => ref.kind === 'peer')

  return (
    <div className="space-y-5">
      <div className="rounded-[12px] border border-collab/20 bg-collab/[0.05] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-collab/12 text-collab">
            <UserRound className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[13.5px] font-semibold text-slate-100">李明的数字员工</h3>
              <span className="text-[11px] text-mint-300">已响应</span>
            </div>
            <p className="mt-1 text-[11.5px] text-slate-500">营销会场设计 · 历史项目复盘</p>
          </div>
        </div>
        <div className="mt-3 space-y-3 border-t border-white/[0.06] pt-3">
          <CollabField label="补充资料" value="2025 年 618 家电会场复盘 · 已确认经验" />
          <CollabField label="贡献判断" value={peerRef?.kind === 'peer' ? peerRef.detail.contribution : '建议避免整屏沉浸式头图，优先保证核心入口可见。'} />
          <CollabField label="授权范围" value="已授权共享的项目复盘经验与团队知识" />
        </div>
      </div>

      <div className="rounded-[12px] border border-collab/20 bg-collab/[0.05] p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-collab/12 text-collab">
            <UserRound className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[13.5px] font-semibold text-slate-100">王晨的数字员工</h3>
              <span className="text-[11px] text-mint-300">已响应</span>
            </div>
            <p className="mt-1 text-[11.5px] text-slate-500">入口数据分析 · 项目指标口径</p>
          </div>
        </div>
        <div className="mt-3 space-y-3 border-t border-white/[0.06] pt-3">
          <CollabField label="补充资料" value="近 90 天首页营销入口点击数据" />
          <CollabField label="贡献判断" value="效率型楼层结构的入口点击表现更优，同时需要进一步确认两组数据的统计口径。" />
          <CollabField label="授权范围" value="已授权共享的项目数据结论，不包含未共享项目资料" />
        </div>
      </div>

      <div className="rounded-[10px] border border-collab/15 bg-collab/[0.04] px-3.5 py-2.5 text-[11.5px] leading-relaxed text-slate-400">
        本次协作只使用同事已授权共享的工作知识和项目资料，不读取私人对话或未授权内容；每项贡献均记录来源。
      </div>
    </div>
  )
}

function ToolMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="shrink-0 text-slate-500">{label}</dt>
      <dd className="text-right leading-relaxed text-slate-300">{value}</dd>
    </div>
  )
}

function CollabField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <p className="mt-0.5 text-[12px] leading-relaxed text-slate-300">{value}</p>
    </div>
  )
}

/* ---------- 本次工作过程 ---------- */

function ProcessBody() {
  const [showTech, setShowTech] = useState(false)
  const a = WORKSPACE_ANALYSIS
  return (
    <div className="space-y-5">
      <Field label="检索了什么">{a.retrieved}</Field>
      <Field label="调用了哪个 Skill">{a.skill}</Field>
      <div>
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
          向哪些数字员工发起协作 · 各自贡献
        </div>
        <div className="space-y-2">
          {a.peers.map((p) => (
            <div
              key={p.name}
              className="rounded-[10px] border border-white/[0.06] bg-surface-1 px-3 py-2.5"
            >
              <div className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-collab">
                <UserRound className="h-3.5 w-3.5" />
                {p.name}
              </div>
              <div className="text-[12px] leading-relaxed text-slate-300">{p.contribution}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-[12px] border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3">
        <div className="mb-1 text-[11px] font-medium text-mint-300">最终如何形成结论</div>
        <div className="text-[13px] leading-relaxed text-slate-300">{a.conclusion}</div>
      </div>

      {/* 技术细节：二级折叠，默认收起 */}
      <div className="rounded-[12px] border border-white/[0.06] bg-surface-1">
        <button
          onClick={() => setShowTech((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left"
        >
          <span className="text-[12px] font-medium text-slate-400">技术执行细节</span>
          <ChevronDown
            className={cn(
              'h-4 w-4 text-slate-500 transition-transform',
              showTech && 'rotate-180',
            )}
          />
        </button>
        {showTech && (
          <div className="space-y-2 border-t border-white/[0.06] px-4 py-3">
            {WORKSPACE_TECH_LOG.map((t) => (
              <div key={t.label}>
                <div className="text-[11px] font-medium text-slate-400">{t.label}</div>
                <div className="mt-0.5 font-mono text-[11px] leading-relaxed text-slate-500">
                  {t.detail}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/* ---------- Brief 预览 ---------- */

function BriefBody() {
  const { showToast } = useDemo()
  return (
    <div className="space-y-5">
      <Field label="项目目标">{BRIEF.goal}</Field>
      <Field label="历史背景">
        <ul className="space-y-1.5">
          {BRIEF.history.map((h, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-500" />
              {h}
            </li>
          ))}
        </ul>
      </Field>
      <Field label="核心问题">{BRIEF.problem}</Field>
      <Field label="设计原则">
        <ol className="space-y-1.5">
          {BRIEF.principles.map((p, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-mint-300">{i + 1}.</span>
              <span>{p}</span>
            </li>
          ))}
        </ol>
      </Field>
      <Field label="设计方向">
        <ul className="space-y-1.5">
          {BRIEF.direction.map((d, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-mint-400/70" />
              {d}
            </li>
          ))}
        </ul>
      </Field>
      <Field label="数据支撑">
        <ul className="space-y-1.5">
          {BRIEF.data.map((d, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-remind/70" />
              {d}
            </li>
          ))}
        </ul>
      </Field>
      <div className="flex gap-2">
        <PanelAction
          icon={FileText}
          label="导出 Brief"
          onClick={() => showToast('Brief 已导出（演示）', 'success')}
        />
      </div>
    </div>
  )
}
