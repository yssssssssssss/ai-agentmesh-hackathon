import { ArrowRight, CheckCircle2, Network, ShieldCheck } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Avatar } from '../ui/Avatar'

interface MyCollabCardProps {
  onDetail: () => void
  status?: 'ongoing' | 'done'
}

const MATCHED_EMPLOYEES = [
  {
    name: '李明的数字员工',
    reason: '参与过 2025 年 618 家电会场项目，并沉淀过相关项目复盘经验。',
    contribution: '补充 2025 年会场项目经验，以及沉浸式头图对首屏入口可见性的影响判断。',
  },
  {
    name: '王晨的数字员工',
    reason: '近期负责首页入口数据分析相关工作。',
    contribution: '补充近 90 天入口点击数据，并提醒进一步确认数据统计口径。',
  },
]

export function MyCollabCard({ onDetail, status = 'done' }: MyCollabCardProps) {
  return (
    <div className="card-base p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            <Network className="h-3.5 w-3.5" />
            618 家电会场协作
          </div>
          <h3 className="mt-1.5 text-[18px] font-semibold text-white">查找 618 家电会场历史经验</h3>
        </div>
        <Badge tone={status === 'done' ? 'mint' : 'knowledge'} dot>{status === 'done' ? '已完成' : '协作中'}</Badge>
      </div>

      <div className="mt-5 border-l-2 border-mint-400/40 pl-3">
        <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">本次协作原因</div>
        <p className="mt-1 text-[13px] leading-relaxed text-slate-300">
          当前项目已经完成基础历史经验检索，但仍缺少 2025 年 618 项目的一线设计经验和近期入口数据，因此数字员工继续向组织内匹配相关数字员工补充信息。
        </p>
      </div>

      <div className="mt-5">
        <div className="mb-3 text-[12px] font-medium text-slate-400">本次匹配的数字员工</div>
        <div className="grid gap-4 md:grid-cols-2">
          {MATCHED_EMPLOYEES.map((employee, index) => (
            <div key={employee.name} className="border-t border-white/[0.06] pt-3">
              <div className="flex items-center gap-2">
                <Avatar name={employee.name} size="sm" tone={index === 0 ? 'knowledge' : 'collab'} className="h-7 w-7 text-[11px]" />
                <h4 className="text-[13.5px] font-semibold text-slate-100">{employee.name}</h4>
              </div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-slate-500"><span className="text-slate-400">匹配原因：</span>{employee.reason}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-500"><span className="text-slate-400">本次贡献：</span>{employee.contribution}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-start gap-2 text-[11.5px] leading-relaxed text-slate-500">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          本次协作仅使用对方已授权共享的项目经验和工作知识，不读取私人对话或未授权资料。
        </div>
      </div>

      <div className="mt-5 border-t border-white/[0.06] pt-4">
        <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">本次协作补全</div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2 text-[12.5px] text-slate-300">
          {['2 个历史项目', '1 组近期入口数据', '1 个数据口径提醒'].map((item) => (
            <span key={item} className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-mint-300" />{item}</span>
          ))}
        </div>
        <div className="mt-4">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">最终用于</div>
          <div className="mt-1 text-[14px] font-semibold text-slate-100">2026 年 618 家电会场首页设计 Brief</div>
          <p className="mt-1 text-[12px] text-slate-500">本次协作补充的经验和数据已进入当前项目判断，并记录在 Brief 的来源依据中。</p>
        </div>
      </div>

      <Button variant="subtle" className="mt-5" iconRight={<ArrowRight className="h-4 w-4" />} onClick={onDetail}>查看协作详情</Button>
    </div>
  )
}
