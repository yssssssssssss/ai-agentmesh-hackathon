import { useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { PageHeader } from '../components/ui/PageHeader'
import { Tabs, type TabItem } from '../components/ui/Tabs'
import { Badge } from '../components/ui/Badge'
import { Avatar } from '../components/ui/Avatar'
import { CollabTimelineDrawer } from '../components/collaboration/CollabTimelineDrawer'
import { useDemo } from '../store/DemoContext'
import { useCollaboration } from '../features/collaboration/useCollaboration'
import type { TaskCard, InboxItem } from '../features/collaboration/api'

const TONES = ['knowledge', 'collab', 'remind', 'mint'] as const

/** 静态能力分布 —— 后端暂无能力聚合接口，保留演示数据 */
const ABILITIES = [
  { label: '项目经验', value: 35 },
  { label: '数据分析', value: 28 },
  { label: '设计方法', value: 22 },
  { label: '业务知识', value: 15 },
]

type Peer = { name: string; tone: (typeof TONES)[number] }

function peerFor(value: string, index: number): Peer {
  return { name: value, tone: TONES[index % TONES.length] }
}

function postTypeLabel(postType: string) {
  const labels: Record<string, string> = { request: '协作请求', evidence: '经验补充', risk: '风险提醒', decision: '决策记录', correction: '修正建议', memory_candidate: '知识候选' }
  return labels[postType] ?? postType
}

function cardParticipants(card: TaskCard) {
  const actor = card.latest_post.actor || card.task.current_owner_agent_id
  return [
    { ...peerFor(actor, 0), ability: postTypeLabel(card.latest_post.post_type), contribution: card.latest_post.content },
  ]
}

function cardStatus(card: TaskCard) {
  return card.task.collaboration_stage === 'completed' ? '已完成' : card.task.collaboration_stage === 'blocked' ? '需关注' : '进行中'
}

function inboxTone(item: InboxItem) {
  return item.item_type === 'risk_review' ? 'remind' : item.item_type === 'tool_call_approval' ? 'knowledge' : 'collab'
}

const ABILITY_COLORS = ['#2dd4a8', '#5b9dff', '#a98bff', '#ffab5e']

function AbilityDonut({ count, abilities }: { count: number; abilities: typeof ABILITIES }) {
  let start = 0
  const segments = abilities.map((a, i) => {
    const end = start + a.value
    const seg = `${ABILITY_COLORS[i]} ${start}% ${end}%`
    start = end
    return seg
  })
  return (
    <div className="relative h-44 w-44 shrink-0 rounded-full" style={{ background: `conic-gradient(${segments.join(', ')})` }}>
      <div className="absolute inset-[24px] flex items-center justify-center rounded-full bg-surface-1">
        <div className="text-center">
          <div className="text-[22px] font-semibold text-white">{count}</div>
          <div className="text-[10.5px] text-slate-500">协作任务</div>
        </div>
      </div>
    </div>
  )
}

export function Collaboration() {
  const { showToast } = useDemo()
  const { taskCards, inboxItems, marketBoard, loading, error, stats, refresh, resolveInbox } = useCollaboration()
  const [detailTab, setDetailTab] = useState('all')
  const [timelineOpen, setTimelineOpen] = useState(false)
  const [activeCard, setActiveCard] = useState<TaskCard | null>(null)
  const [declined, setDeclined] = useState(false)
  const [overviewPeriod, setOverviewPeriod] = useState('month')
  const [abilityPeriod, setAbilityPeriod] = useState('month')

  const openRequests = inboxItems.filter((i) => i.status === 'open')

  const detailTabs: TabItem[] = [
    { key: 'all', label: '全部协作' },
    { key: 'requests', label: '我的申请', count: openRequests.filter((i) => i.item_type !== 'decision_review' && i.item_type !== 'risk_review').length || undefined },
    { key: 'authorize', label: '待我授权', count: openRequests.filter((i) => i.item_type === 'decision_review' || i.item_type === 'risk_review').length || undefined },
  ]

  const displayedCards = detailTab === 'all' ? taskCards : []

  const handleAllow = async (item: InboxItem) => {
    try {
      await resolveInbox(item.id)
      showToast('已允许本次使用，原知识默认权限不变')
    } catch (e) {
      showToast('授权失败，请重试', 'info')
    }
  }

  const handleDecline = () => {
    setDeclined(true)
    showToast('已拒绝本次使用，原知识默认权限不变', 'info')
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="协作网络"
        subtitle="数字员工会根据任务需要，在授权范围内自动连接组织中的经验与能力；只有涉及个人未共享知识时，才需要本人授权。"
      />

      {loading && <div className="text-sm text-slate-400">加载中…</div>}
      {error && <div className="text-sm text-red-300">加载失败：{error} <button type="button" onClick={refresh} className="underline">重试</button></div>}

      <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <section className="card-base p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <SectionHeading title="我的协作网络" desc="数字员工之间自动完成的经验连接与授权协作。" />
            <PeriodTabs value={overviewPeriod} onChange={setOverviewPeriod} />
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <NetworkMetric value={`${stats.completed} 次`} label="本月完成协作" desc="数字员工之间已自动完成的协作" />
            <NetworkMetric value={`${stats.pendingAuths} 个`} label="私人知识授权" desc="需要本人处理的未共享知识请求" remind />
            <PeopleMetric label="获得经验支持" value="6 位" desc="为我的任务提供过知识或判断" peers={taskCards.slice(0, 5).map((c, i) => peerFor(c.latest_post.actor || c.task.current_owner_agent_id, i))} overflow={`+${Math.max(0, taskCards.length - 5)}`} />
            <PeopleMetric label="我的经验帮助" value="9 位" desc="授权知识被其他数字员工用于工作" peers={taskCards.slice(0, 5).map((c, i) => peerFor(c.task.current_owner_agent_id, i))} overflow={`+${Math.max(0, marketBoard?.counts.matches ?? 0)}`} />
          </div>
        </section>

        <section className="card-base p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <SectionHeading title="协作能力类型" desc="数字员工从组织网络中补充的能力分布。" />
            <PeriodTabs value={abilityPeriod} onChange={setAbilityPeriod} />
          </div>
          <div className="flex flex-col items-center gap-5 sm:flex-row sm:justify-center">
            <AbilityDonut count={stats.total} abilities={ABILITIES} />
            <div className="w-full space-y-2.5">
              {ABILITIES.map((ability, index) => (
                <div key={ability.label} className="flex items-center justify-between gap-4 text-[12px]">
                  <span className="flex items-center gap-2 text-slate-300">
                    <span className={`h-2.5 w-2.5 rounded-full ${['bg-mint-400', 'bg-knowledge', 'bg-collab', 'bg-remind'][index]}`} />
                    {ability.label}
                  </span>
                  <span className="tabular-nums text-slate-500">{ability.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      <section>
        <SectionHeading title="协作明细" desc="查看数字员工自动完成的协作，以及涉及私人知识时产生的授权记录。" />
        <Tabs items={detailTabs} value={detailTab} onChange={setDetailTab} />

        <div className="mt-4 animate-fade-in">
          {detailTab === 'all' && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {displayedCards.length === 0 && !loading && (
                <div className="card-base py-12 text-center text-sm text-slate-400 md:col-span-2 xl:col-span-3">暂无协作记录</div>
              )}
              {displayedCards.map((card) => (
                <CollaborationRecord
                  key={card.task.id}
                  title={card.task.title}
                  request={card.latest_post.content}
                  participants={cardParticipants(card)}
                  supplements={card.latest_post.title}
                  status={cardStatus(card)}
                  onDetail={() => {
                    setActiveCard(card)
                    setTimelineOpen(true)
                  }}
                />
              ))}
            </div>
          )}

          {detailTab === 'requests' && <MyKnowledgeRequest />}

          {detailTab === 'authorize' && !declined && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {openRequests.filter((i) => i.item_type === 'decision_review' || i.item_type === 'risk_review').length === 0 && (
                <div className="card-base py-12 text-center text-sm text-slate-400 md:col-span-2 xl:col-span-3">当前没有待授权请求</div>
              )}
              {openRequests
                .filter((i) => i.item_type === 'decision_review' || i.item_type === 'risk_review')
                .map((item) => (
                  <AuthorizationRequest
                    key={item.id}
                    item={item}
                    authorized={false}
                    onAllow={() => handleAllow(item)}
                    onDecline={handleDecline}
                  />
                ))}
            </div>
          )}

          {detailTab === 'authorize' && declined && (
            <div className="card-base py-12 text-center text-sm text-slate-400">当前没有待授权请求</div>
          )}
        </div>
      </section>

      <CollabTimelineDrawer open={timelineOpen} onClose={() => setTimelineOpen(false)} card={activeCard} />
    </div>
  )
}

function PeriodTabs({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const options = [
    { key: 'month', label: '本月' },
    { key: 'quarter', label: '近 3 个月' },
    { key: 'halfYear', label: '近半年' },
  ]
  return (
    <div className="inline-flex items-center gap-1 rounded-[9px] bg-white/[0.03] p-1">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          onClick={() => onChange(option.key)}
          className={value === option.key
            ? 'rounded-[7px] bg-mint-400/[0.12] px-2.5 py-1.5 text-[11px] font-medium text-mint-300'
            : 'rounded-[7px] px-2.5 py-1.5 text-[11px] text-slate-500 transition-colors hover:text-slate-300'}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function SectionHeading({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-[16px] font-semibold text-slate-100">{title}</h2>
      <p className="mt-0.5 text-[12px] text-slate-500">{desc}</p>
    </div>
  )
}

function PeopleMetric({ label, value, desc, peers, overflow }: { label: string; value: string; desc: string; peers: Peer[]; overflow: string }) {
  return (
    <div className="border-b border-white/[0.06] pb-3 sm:border-0 sm:pb-0">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[12px] text-slate-400">{label}</div>
          <p className="mt-0.5 text-[10.5px] text-slate-600">{desc}</p>
        </div>
        <span className="shrink-0 text-[18px] font-semibold text-white">{value}</span>
      </div>
      <div className="mt-3 flex -space-x-2">
        {peers.slice(0, 5).map((peer) => (
          <Avatar key={peer.name} name={peer.name} size="sm" tone={peer.tone} className="h-8 w-8 border-2 border-surface-1 text-[10px]" />
        ))}
        <span className="relative inline-flex h-8 w-8 items-center justify-center rounded-full border-2 border-surface-1 bg-surface-3 text-[10px] font-medium text-slate-300">{overflow}</span>
      </div>
    </div>
  )
}

function NetworkMetric({ value, label, desc, remind }: { value: string; label: string; desc: string; remind?: boolean }) {
  return (
    <div className="border-b border-white/[0.06] pb-3 last:border-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12px] text-slate-400">{label}</span>
        <span className={remind ? 'text-[18px] font-semibold text-remind' : 'text-[18px] font-semibold text-white'}>{value}</span>
      </div>
      <p className="mt-0.5 text-[10.5px] text-slate-600">{desc}</p>
    </div>
  )
}

interface Participant {
  name: string
  tone: 'mint' | 'knowledge' | 'collab' | 'remind'
  ability: string
  contribution: string
}

function CollaborationRecord({
  title,
  request,
  participants,
  supplements,
  status,
  onDetail,
}: {
  title: string
  request: string
  participants: Participant[]
  supplements: string
  status: string
  onDetail: () => void
}) {
  const tone = status === '已完成' ? 'mint' : status === '需关注' ? 'remind' : 'knowledge'
  return (
    <article className="group card-base relative flex min-h-[260px] flex-col p-5 transition-all duration-150 hover:-translate-y-0.5 hover:border-white/[0.14] hover:bg-surface-2">
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-[15px] font-semibold leading-snug text-slate-100">{title}</h3>
        <Badge tone={tone}>{status}</Badge>
      </div>
      <p className="mt-3 text-[12.5px] leading-relaxed text-slate-400">{request}</p>

      <div className="mt-3">
        <div className="text-[10.5px] uppercase tracking-wide text-slate-600">本次获得</div>
        <p className="mt-1 text-[12px] leading-relaxed text-slate-300">{supplements}</p>
      </div>

      <div className="mt-auto flex items-end justify-between gap-3 border-t border-white/[0.06] pt-4">
        <ParticipantGroup participants={participants} />
        <button type="button" onClick={onDetail} className="mb-1 inline-flex items-center gap-1 text-[12px] text-slate-500 transition-colors group-hover:text-mint-300">
          查看协作详情 <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </article>
  )
}

function ParticipantGroup({ participants }: { participants: Participant[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative mt-2 w-fit" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <div className="flex -space-x-2">
        {participants.slice(0, 3).map((participant) => (
          <Avatar key={participant.name} name={participant.name} size="sm" tone={participant.tone} className="h-8 w-8 border-2 border-surface-2 text-[10px]" />
        ))}
        {participants.length > 3 && <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border-2 border-surface-2 bg-surface-3 text-[10px] text-slate-300">+{participants.length - 3}</span>}
      </div>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-2 w-[320px] rounded-[12px] border border-white/[0.08] bg-surface-2 p-4 shadow-pop animate-fade-in">
          <div className="mb-3 text-[12px] font-medium text-slate-200">参与本次协作的数字员工</div>
          <div className="space-y-3">
            {participants.map((participant) => (
              <div key={participant.name} className="flex gap-3 border-t border-white/[0.05] pt-3 first:border-0 first:pt-0">
                <Avatar name={participant.name} size="sm" tone={participant.tone} />
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-medium text-slate-100">{participant.name}</div>
                  <div className="mt-0.5 text-[10.5px] text-slate-600">{participant.ability}</div>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-slate-400">提供：{participant.contribution}</p>
                  <button type="button" className="mt-1 text-[11.5px] text-slate-500 hover:text-mint-300">查看明细 →</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MyKnowledgeRequest() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <article className="card-base min-h-[260px] p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Avatar name="李明的数字员工" size="sm" tone="knowledge" />
            <div>
              <div className="text-[11px] text-slate-500">对方数字员工</div>
              <h3 className="text-[14px] font-semibold text-slate-100">李明的数字员工</h3>
            </div>
          </div>
          <Badge tone="remind" dot>等待授权</Badge>
        </div>

        <div className="mt-4">
          <div className="text-[11px] text-slate-500">申请知识</div>
          <div className="mt-1 text-[13.5px] font-medium text-slate-200">「2025 年 618 会场个人复盘」</div>
        </div>

        <div className="mt-3">
          <div className="text-[11px] text-slate-500">使用场景</div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-slate-300">用于 2026 年 618 家电会场首页改版，补充一线项目经验和首屏结构判断。</p>
        </div>

        <div className="mt-4 border-t border-white/[0.06] pt-4 text-[12px] text-slate-500">
          等待对方允许
        </div>
      </article>
    </div>
  )
}

function AuthorizationRequest({
  item,
  authorized,
  onAllow,
  onDecline,
}: {
  item: InboxItem
  authorized: boolean
  onAllow: () => void
  onDecline: () => void
}) {
  const applicant = item.metadata?.applicant as string | undefined ?? '对方数字员工'
  const tone = inboxTone(item)
  const knowledge = item.title
  const scenario = item.summary
  return (
    <article className="card-base min-h-[260px] p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Avatar name={applicant} size="sm" tone={tone} />
          <div>
            <div className="text-[11px] text-slate-500">申请人</div>
            <h3 className="text-[14px] font-semibold text-slate-100">{applicant}</h3>
          </div>
        </div>
        <Badge tone={authorized ? 'mint' : 'remind'} dot>{authorized ? '已允许' : '等待授权'}</Badge>
      </div>

      <div className="mt-4">
        <div className="text-[11px] text-slate-500">申请知识</div>
        <div className="mt-1 text-[13.5px] font-medium text-slate-200">「{knowledge}」</div>
      </div>

      <div className="mt-3">
        <div className="text-[11px] text-slate-500">使用场景</div>
        <p className="mt-1 text-[12.5px] leading-relaxed text-slate-300">{scenario}</p>
      </div>

      {!authorized && (
        <div className="mt-4 grid grid-cols-2 gap-2.5 border-t border-white/[0.06] pt-4">
          <button
            type="button"
            onClick={onAllow}
            className="flex h-10 w-full items-center justify-center rounded-[10px] bg-mint-400 px-4 text-[#06231c] transition-colors hover:bg-mint-300"
          >
            <span className="text-[14px] font-semibold">允许</span>
          </button>
          <button
            type="button"
            onClick={onDecline}
            className="flex h-10 w-full items-center justify-center rounded-[10px] border border-white/[0.08] bg-surface-1 px-4 text-[13px] font-medium text-white transition-colors hover:bg-surface-3"
          >
            驳回
          </button>
        </div>
      )}
    </article>
  )
}
