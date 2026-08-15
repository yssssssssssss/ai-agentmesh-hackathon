import {
  BookMarked,
  Target,
  ShieldCheck,
  ShieldAlert,
  Check,
  FileSearch,
  CheckCircle2,
  BadgeCheck,
} from 'lucide-react'
import { Avatar } from '../ui/Avatar'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import type { HelpRequest } from '../../data/mockData'

interface HelpRequestCardProps {
  request: HelpRequest
  authorized: boolean
  onAllow: () => void
  onDetail: () => void
  onDecline: () => void
  featured?: boolean
}

function Row({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 shrink-0 text-slate-500">{icon}</span>
      <div className="text-sm leading-relaxed">
        <span className="text-slate-500">{label}：</span>
        <span className="text-slate-300">{children}</span>
      </div>
    </div>
  )
}

export function HelpRequestCard({
  request,
  authorized,
  onAllow,
  onDetail,
  onDecline,
  featured,
}: HelpRequestCardProps) {
  const { applicant, knowledgeMeta } = request
  return (
    <div className={`card-base p-5 transition-colors ${featured ? 'border-collab/25 bg-collab/[0.04]' : ''}`}>
      {/* 谁想使用 · 用于什么项目 */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Avatar name={applicant} tone="collab" size="lg" />
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-white">{request.from}申请引用你的知识</h3>
              {featured && <Badge tone="collab">重点协作</Badge>}
            </div>
            <p className="mt-0.5 text-sm text-slate-400">用于「{request.project}」</p>
          </div>
        </div>
        {authorized ? (
          <Badge tone="mint" icon={<CheckCircle2 className="h-3.5 w-3.5" />}>
            已授权
          </Badge>
        ) : (
          <Badge tone="remind" dot>
            等待确认
          </Badge>
        )}
      </div>

      {/* 哪条知识（含溯源）· 使用目的 · 本次授权 */}
      <div className="mt-4 space-y-3 rounded-[12px] bg-surface-2 p-4">
        <div className="flex gap-2.5">
          <BookMarked className="mt-0.5 h-4 w-4 shrink-0 text-knowledge" />
          <div className="min-w-0">
            <div className="text-sm">
              <span className="text-slate-500">申请引用：</span>
              <span className="font-medium text-slate-100">{request.knowledge}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1 text-mint-300">
                <BadgeCheck className="h-3 w-3" />
                {knowledgeMeta.verified}
              </span>
              <span className="text-slate-700">·</span>
              <span>当前权限：{knowledgeMeta.permission}</span>
              <span className="text-slate-700">·</span>
              <span>原始贡献者：{knowledgeMeta.contributor}</span>
              <span className="text-slate-700">·</span>
              <span>最近验证：{knowledgeMeta.lastVerified}</span>
            </div>
          </div>
        </div>

        <Row icon={<Target className="h-4 w-4" />} label="使用目的">
          {request.purpose}
        </Row>
        <Row icon={<ShieldCheck className="h-4 w-4" />} label="本次授权">
          {request.authorization}
        </Row>
      </div>

      {/* 数字人提醒 */}
      <div className="mt-3 flex items-start gap-2.5 rounded-[10px] border border-remind/20 bg-remind/[0.05] px-3.5 py-2.5">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-remind" />
        <p className="text-xs leading-relaxed text-remind">数字人提醒：{request.risk}</p>
      </div>

      {authorized ? (
        <div className="mt-4 flex items-start gap-2 rounded-[10px] bg-mint-400/[0.06] px-4 py-3 text-sm text-mint-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          你的数字人已在「{request.project}」中把「{request.knowledge}」提供给{applicant}，并保留来源和适用范围。
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2.5">
          <Button variant="primary" icon={<Check className="h-4 w-4" />} onClick={onAllow}>
            允许本次引用
          </Button>
          <Button variant="subtle" icon={<FileSearch className="h-4 w-4" />} onClick={onDetail}>
            查看知识与项目
          </Button>
          <Button variant="ghost" onClick={onDecline}>
            拒绝本次引用
          </Button>
        </div>
      )}
    </div>
  )
}
