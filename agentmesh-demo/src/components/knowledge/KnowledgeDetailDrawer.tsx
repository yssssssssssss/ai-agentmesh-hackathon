import { type ReactNode } from 'react'
import {
  BookOpen,
  Quote,
  Lightbulb,
  ClipboardList,
  Sparkles,
  Users,
  ShieldCheck,
  History,
  FileText,
  AlertCircle,
  Target,
  User as UserIcon,
} from 'lucide-react'
import { Drawer } from '../ui/Drawer'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import {
  KNOWLEDGE_TYPE_LABELS,
  NEW_KNOWLEDGE,
  VISIBILITY_LABELS,
  type KnowledgeAsset,
  type ShareEvent,
} from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'

export type DrawerTarget =
  | { kind: 'asset'; asset: KnowledgeAsset }
  | { kind: 'candidate' }
  | { kind: 'event'; event: ShareEvent }

interface Props {
  open: boolean
  onClose: () => void
  target: DrawerTarget | null
  /** Tab 2 场景:候选卡打开抽屉时可能想快速回到"确认并沉淀"入口 */
  onOpenConfirm?: () => void
}

/**
 * 我的知识 · 统一详情抽屉。
 * 知识资产、待确认候选和共享动态都可以打开此抽屉(修改文档 §11)。
 * 主要区域按以下顺序:
 *   知识标题 / 状态 / 类型 / 权限
 *   核心结论
 *   解决的问题
 *   形成依据(证据 / 依据数据)
 *   适用范围与限制条件
 *   来源与贡献者(知识谱系,不将他人贡献归属给当前用户)
 *   共享和引用记录
 *   操作
 */
export function KnowledgeDetailDrawer({ open, onClose, target, onOpenConfirm }: Props) {
  const { assets } = useDemo()

  if (!open || !target) {
    // Drawer 自身通过 open 控制显隐,这里只需要保证不 crash
    return <Drawer open={false} onClose={onClose}>{null}</Drawer>
  }

  // 统一抽取"上下文":候选场景 → 用 NEW_KNOWLEDGE,资产 / 事件 → 用对应 asset
  const isCandidate = target.kind === 'candidate'
  const asset =
    target.kind === 'asset'
      ? target.asset
      : target.kind === 'event'
        ? assets.find((a) => a.id === target.event.knowledgeId)
        : null
  const event = target.kind === 'event' ? target.event : null

  const title = isCandidate ? NEW_KNOWLEDGE.title : asset?.title ?? '知识详情'
  const conclusion = isCandidate ? NEW_KNOWLEDGE.conclusion : asset?.conclusion ?? ''
  const typeLabel = isCandidate
    ? NEW_KNOWLEDGE.suggestedTypeLabel
    : asset
      ? KNOWLEDGE_TYPE_LABELS[asset.type]
      : ''
  const statusLabel = isCandidate ? '待确认' : '已沉淀'
  const statusTone: 'remind' | 'mint' = isCandidate ? 'remind' : 'mint'

  const visibilityLabel = isCandidate
    ? '未设置'
    : asset
      ? asset.visibility === 'team' && asset.visibilityDetail
        ? `已共享给 ${asset.visibilityDetail}`
        : VISIBILITY_LABELS[asset.visibility]
      : ''

  const problem = isCandidate ? NEW_KNOWLEDGE.problem : asset?.problem
  const evidence = isCandidate
    ? NEW_KNOWLEDGE.rawData.map((d) => `${d.label}:${d.value}`)
    : asset?.evidence
  const scope = isCandidate ? NEW_KNOWLEDGE.scope.join('、') : asset?.scope
  const limitation = isCandidate ? NEW_KNOWLEDGE.limitation : asset?.limitation
  const sourceProject = isCandidate ? NEW_KNOWLEDGE.sourceProject : asset?.sourceProject
  const contributor = isCandidate ? NEW_KNOWLEDGE.contributor : asset?.contributor
  const verified = isCandidate ? '等待本人确认' : asset?.verified
  const updated = isCandidate ? '项目复盘完成后' : asset?.updated

  const citations = !isCandidate && asset ? asset.citations ?? [] : []

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={520}
      icon={<BookOpen className="h-5 w-5" />}
      title={title}
      subtitle={sourceProject ? `来源:${sourceProject}` : undefined}
      footer={
        isCandidate ? (
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs text-slate-500">候选阶段:所有引用与共享须经本人确认</div>
            <Button variant="primary" size="sm" onClick={onOpenConfirm}>
              去确认并沉淀
            </Button>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-6">
        {/* ── 状态 / 类型 / 权限 ── */}
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={statusTone} dot>
            {statusLabel}
          </Badge>
          {typeLabel && <Badge tone="knowledge">{typeLabel}</Badge>}
          <Badge tone={isCandidate ? 'neutral' : asset?.visibility === 'private' ? 'neutral' : 'collab'}>
            {visibilityLabel}
          </Badge>
          {!isCandidate && asset?.hasNewFeedback && (
            <Badge tone="remind" dot>
              有新反馈
            </Badge>
          )}
        </div>

        {/* ── 事件说明(仅事件模式) ── */}
        {event && (
          <SectionBlock icon={<Sparkles className="h-4 w-4" />} label="本次动态">
            <p className="text-sm leading-relaxed text-slate-300">{event.description}</p>
            {event.detail && (
              <p className="mt-2 text-[12.5px] leading-relaxed text-slate-500">{event.detail}</p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <UserIcon className="h-3.5 w-3.5" />
              {event.actor} · {event.project} · {event.time}
            </div>
          </SectionBlock>
        )}

        {/* ── 核心结论 ── */}
        <SectionBlock icon={<Quote className="h-4 w-4" />} label="核心结论">
          <p className="text-[14.5px] font-medium leading-relaxed text-slate-100">{conclusion}</p>
        </SectionBlock>

        {/* ── 解决的问题 ── */}
        {problem && (
          <SectionBlock icon={<AlertCircle className="h-4 w-4" />} label="解决的问题">
            <p className="text-sm leading-relaxed text-slate-300">{problem}</p>
          </SectionBlock>
        )}

        {/* ── 形成依据 ── */}
        {evidence && evidence.length > 0 && (
          <SectionBlock icon={<ClipboardList className="h-4 w-4" />} label="形成依据">
            <ul className="space-y-2">
              {evidence.map((e) => (
                <li key={e} className="flex gap-2 text-sm text-slate-300">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-500" />
                  {e}
                </li>
              ))}
            </ul>
          </SectionBlock>
        )}

        {/* ── 适用范围与限制条件 ── */}
        {(scope || limitation) && (
          <SectionBlock icon={<Target className="h-4 w-4" />} label="适用范围与限制条件">
            {scope && (
              <div>
                <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                  适用范围
                </div>
                <p className="mt-1 text-sm leading-relaxed text-slate-300">{scope}</p>
              </div>
            )}
            {limitation && (
              <div className={scope ? 'mt-3' : undefined}>
                <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                  限制条件
                </div>
                <p className="mt-1 text-sm leading-relaxed text-slate-300">{limitation}</p>
              </div>
            )}
          </SectionBlock>
        )}

        {/* ── 来源与贡献者(知识谱系) ── */}
        <SectionBlock icon={<Users className="h-4 w-4" />} label="来源与贡献者">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <MetaRow label="原始项目" value={sourceProject ?? '—'} />
            <MetaRow label="原始贡献者" value={contributor ?? '—'} />
            <MetaRow label="验证状态" value={verified ?? '—'} />
            <MetaRow label="最近更新" value={updated ?? '—'} />
            {isCandidate && (
              <MetaRow
                label="形成方式"
                value={NEW_KNOWLEDGE.formationMethod}
                full
              />
            )}
          </dl>
        </SectionBlock>

        {/* ── 知识反馈：新结果不会自动覆盖原知识 ── */}
        {!isCandidate && asset?.hasNewFeedback && (
          <SectionBlock icon={<Lightbulb className="h-4 w-4" />} label="知识反馈">
            <div className="space-y-3">
              <div>
                <div className="text-[11px] uppercase tracking-wide text-slate-500">当前知识</div>
                <p className="mt-1 text-sm leading-relaxed text-slate-300">{asset.conclusion}</p>
              </div>
              <div className="border-l-2 border-remind/50 pl-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">新反馈</div>
                <p className="mt-1 text-sm leading-relaxed text-slate-300">
                  来自「内容导购频道改版」：部分强任务场景下，首屏超过 6 张导购卡仍保持较好点击表现，建议重新验证适用范围。
                </p>
              </div>
              <p className="text-[12px] leading-relaxed text-slate-500">新反馈不会自动修改原知识，需要重新确认后才能更新结论或适用范围。</p>
              <div className="flex gap-2">
                <Button variant="subtle" size="sm">查看反馈</Button>
                <Button variant="secondary" size="sm">发起知识更新</Button>
              </div>
            </div>
          </SectionBlock>
        )}

        {/* ── 共享和引用记录 ── */}
        {!isCandidate && (
          <SectionBlock icon={<History className="h-4 w-4" />} label="共享和引用记录">
            {citations.length === 0 ? (
              <p className="text-sm text-slate-500">尚未被引用。授权后其他数字人才能使用这条知识。</p>
            ) : (
              <ol className="space-y-2.5">
                {citations.map((c, i) => (
                  <li
                    key={`${c.who}-${c.project}-${i}`}
                    className="flex items-start gap-3 rounded-[10px] border border-white/[0.06] bg-surface-1 p-3"
                  >
                    <span className="mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-collab/12 text-collab">
                      <UserIcon className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-slate-100">{c.who}</span>
                        <span className="text-xs text-slate-500">· {c.project}</span>
                      </div>
                      {c.purpose && (
                        <p className="mt-0.5 text-xs text-slate-500">用途:{c.purpose}</p>
                      )}
                    </div>
                    <span className="shrink-0 text-[11px] text-slate-500">{c.time}</span>
                  </li>
                ))}
              </ol>
            )}
          </SectionBlock>
        )}

        {/* ── 操作(仅资产 / 事件模式,候选场景操作放在底部主按钮) ── */}
        {!isCandidate && (
          <SectionBlock icon={<ShieldCheck className="h-4 w-4" />} label="可用操作">
            <div className="flex flex-wrap gap-2">
              <Button variant="subtle" size="sm" icon={<FileText className="h-3.5 w-3.5" />}>
                编辑知识
              </Button>
              <Button variant="subtle" size="sm" icon={<ShieldCheck className="h-3.5 w-3.5" />}>
                调整权限
              </Button>
              <Button variant="subtle" size="sm" icon={<History className="h-3.5 w-3.5" />}>
                查看完整复盘
              </Button>
              <Button variant="subtle" size="sm" icon={<Lightbulb className="h-3.5 w-3.5" />}>
                发起更新
              </Button>
            </div>
          </SectionBlock>
        )}
      </div>
    </Drawer>
  )
}

function SectionBlock({
  icon,
  label,
  children,
}: {
  icon: ReactNode
  label: string
  children: ReactNode
}) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
        <span className="text-slate-500">{icon}</span>
        {label}
      </div>
      {children}
    </section>
  )
}

function MetaRow({ label, value, full }: { label: string; value: string; full?: boolean }) {
  return (
    <div className={full ? 'col-span-2' : undefined}>
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-200">{value}</dd>
    </div>
  )
}
