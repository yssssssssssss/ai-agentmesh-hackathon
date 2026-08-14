import { useEffect, useMemo, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { CheckCircle2, ArrowRight } from 'lucide-react'
import { PageHeader } from '../components/ui/PageHeader'
import { Tabs, type TabItem } from '../components/ui/Tabs'
import { Button } from '../components/ui/Button'
import { AssetsPanel } from '../components/knowledge/AssetsPanel'
import { PendingCandidatePanel } from '../components/knowledge/PendingCandidatePanel'
import { ShareTimeline } from '../components/knowledge/ShareTimeline'
import { ConfirmKnowledgeModal } from '../components/knowledge/ConfirmKnowledgeModal'
import {
  KnowledgeDetailDrawer,
  type DrawerTarget,
} from '../components/knowledge/KnowledgeDetailDrawer'
import { useDemo } from '../store/DemoContext'
import type { KnowledgeAsset, ShareEvent } from '../data/mockData'

/**
 * 我的知识(修改文档 §7):
 *   Tabs = 知识资产 24 / 待我确认 1 / 共享与引用 9
 * 默认 tab 逻辑:
 *   ?tab=pending      → 待我确认(工作洞察 → 前往我的知识 落地此处)
 *   ?tab=shared       → 共享与引用(协作页 落地此处)
 *   ?tab=assets 或 无 → 知识资产
 * 三个面板都通过统一详情抽屉 KnowledgeDetailDrawer 打开详情。
 */
type TabKey = 'assets' | 'pending' | 'shared'

function normalizeTab(input: string | null | undefined): TabKey {
  if (input === 'pending' || input === 'shared' || input === 'assets') return input
  return 'assets'
}

export function Knowledge() {
  const {
    assets,
    assetCount,
    pendingCount,
    shareEvents,
    shareEventCount,
  } = useDemo()

  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation() as { state?: { tab?: string } | null }
  const initialTab = normalizeTab(searchParams.get('tab') ?? location.state?.tab)
  const [tab, setTab] = useState<TabKey>(initialTab)

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [drawerTarget, setDrawerTarget] = useState<DrawerTarget | null>(null)

  // 保证 URL 与内部 state 一致;不修改浏览器历史(replace),避免污染返回栈。
  useEffect(() => {
    const urlTab = normalizeTab(searchParams.get('tab'))
    if (urlTab !== tab) {
      const next = new URLSearchParams(searchParams)
      if (tab === 'assets') next.delete('tab')
      else next.set('tab', tab)
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  // 若外部通过 state 传入了 tab,同步一次
  useEffect(() => {
    const s = location.state?.tab
    if (s) {
      const next = normalizeTab(s)
      if (next !== tab) setTab(next)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

  const tabs: TabItem[] = useMemo(
    () => [
      { key: 'assets', label: '已沉淀知识', count: assetCount },
      { key: 'pending', label: '待我确认', count: pendingCount },
      { key: 'shared', label: '使用与反馈', count: shareEventCount },
    ],
    [assetCount, pendingCount, shareEventCount],
  )

  const openAsset = (a: KnowledgeAsset) => setDrawerTarget({ kind: 'asset', asset: a })
  const openCandidate = () => setDrawerTarget({ kind: 'candidate' })
  const openEvent = (e: ShareEvent) => setDrawerTarget({ kind: 'event', event: e })
  const closeDrawer = () => setDrawerTarget(null)

  const openConfirmFromDrawer = () => {
    closeDrawer()
    setConfirmOpen(true)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="我的知识"
        subtitle="经过你确认并从真实工作中沉淀的经验，可被数字员工在后续项目中检索、引用和复用。"
      />

      <Tabs items={tabs} value={tab} onChange={(k) => setTab(k as TabKey)} />

      {/* ── Tab 1 · 知识资产 ── */}
      {tab === 'assets' && (
        <AssetsPanel assets={assets} totalCount={assetCount} onOpenAsset={openAsset} />
      )}

      {/* ── Tab 2 · 待我确认 ── */}
      {tab === 'pending' && (
        <>
          {pendingCount > 0 ? (
            <PendingCandidatePanel
              onConfirm={() => setConfirmOpen(true)}
              onModify={() => setConfirmOpen(true)}
              onOpenDetail={openCandidate}
            />
          ) : (
            <div className="card-base flex flex-col items-center py-14 text-center animate-fade-in">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-mint-400/12 text-mint-300">
                <CheckCircle2 className="h-7 w-7" />
              </span>
              <h3 className="mt-4 text-base font-semibold text-white">待确认知识已全部处理</h3>
              <p className="mt-1.5 max-w-md text-sm text-slate-400">
                最近来自「消息活动日历改版」的复盘结论已确认并沉淀。你可以在
                <span className="text-slate-200">知识资产</span> 或
                <span className="text-slate-200">共享与引用</span> 中查看后续被引用情况。
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={<ArrowRight className="h-4 w-4" />}
                  onClick={() => setTab('assets')}
                >
                  查看知识资产
                </Button>
                <Button
                  variant="subtle"
                  size="sm"
                  onClick={() => setTab('shared')}
                >
                  查看共享动态
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Tab 3 · 共享与引用 ── */}
      {tab === 'shared' && (
        <ShareTimeline
          events={shareEvents}
          totalCount={shareEventCount}
          onOpenEvent={openEvent}
        />
      )}

      {/* 3 步确认弹窗 */}
      <ConfirmKnowledgeModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onDone={() => {
          // 确认完成后停留在待我确认(此时 pendingCount=0,空态引导到知识资产)
          setTab('assets')
        }}
      />

      {/* 统一详情抽屉:资产 / 候选 / 动态共用 */}
      <KnowledgeDetailDrawer
        open={drawerTarget !== null}
        target={drawerTarget}
        onClose={closeDrawer}
        onOpenConfirm={openConfirmFromDrawer}
      />
    </div>
  )
}
