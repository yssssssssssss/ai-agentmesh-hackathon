import { useNavigate } from 'react-router-dom'
import { CheckCircle2, CircleDot, Circle, ChevronRight, ListTodo } from 'lucide-react'
import { SectionCard } from '../ui/Card'
import { TODAY_WORK } from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'
import { cn } from '../../lib/cn'

const STATUS_MAP = {
  done: { label: '已完成', icon: CheckCircle2, cls: 'text-mint-300' },
  doing: { label: '进行中', icon: CircleDot, cls: 'text-knowledge' },
  pending: { label: '待处理', icon: Circle, cls: 'text-remind' },
}

export function TodayWork() {
  const navigate = useNavigate()
  const { pendingCount } = useDemo()

  return (
    <SectionCard title="今日工作" icon={<ListTodo className="h-[18px] w-[18px]" />}>
      <div className="space-y-2">
        {TODAY_WORK.map((item) => {
          // 第三项"确认新提炼的项目经验"在已确认后状态转为已完成
          const status =
            item.id === 't-3' && pendingCount === 0 ? 'done' : item.status
          const meta = STATUS_MAP[status]
          const Icon = meta.icon
          const clickable = Boolean(item.to)
          return (
            <button
              key={item.id}
              disabled={!clickable}
              onClick={() => item.to && navigate(item.to)}
              className={cn(
                'flex w-full items-center gap-3 rounded-[12px] border border-white/[0.06] bg-surface-2 px-4 py-3 text-left transition-all',
                clickable && 'hover:border-white/[0.12] hover:bg-surface-3',
                !clickable && 'cursor-default',
              )}
            >
              <Icon className={cn('h-[18px] w-[18px] shrink-0', meta.cls)} />
              <span className="flex-1 text-sm text-slate-200">{item.title}</span>
              <span className={cn('text-xs font-medium', meta.cls)}>{meta.label}</span>
              {clickable && <ChevronRight className="h-4 w-4 text-slate-600" />}
            </button>
          )
        })}
      </div>
    </SectionCard>
  )
}
