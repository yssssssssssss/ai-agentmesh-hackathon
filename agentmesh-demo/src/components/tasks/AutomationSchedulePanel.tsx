import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { queryKeys, type QueryScope } from '../../app/queryKeys'
import { automationApi, type AutomationStatus, type InspectionRun, type InspectionSchedule } from '../../features/tasks/automationApi'
import { taskManagementErrorMessage } from '../../features/tasks/queries'
import type { InspectionTemplate } from '../../features/tasks/types'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { ProjectInspectionView, TEMPLATES } from './ProjectInspectionPanel'

const FIELD = 'mt-1 w-full rounded-control border border-white/10 bg-surface-1 px-3 py-2 text-sm text-slate-100'
const MODES = { off: '自动执行已关闭', observe: '仅观察到期配置', execute: '自动执行已开启' }
const RUN_STATES: Record<string, string> = {
  created: '等待执行', running: '正在读取', completed: '读取完成', failed: '执行失败', cancelled: '已取消',
  partial: '部分完成', skipped: '本次跳过', blocked: '执行条件未满足',
}

function time(value: string | null | undefined, timezone = 'Asia/Shanghai') {
  if (!value) return '未安排'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: timezone, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value))
}

interface ListProps {
  schedules: InspectionSchedule[]
  status?: AutomationStatus
  userId: string
  busy: boolean
  onToggle: (schedule: InspectionSchedule) => void
  onRun: (schedule: InspectionSchedule) => void
  onHistory: (schedule: InspectionSchedule) => void
  onEdit: (schedule: InspectionSchedule) => void
}

export function AutomationScheduleList({ schedules, status, userId, busy, onToggle, onRun, onHistory, onEdit }: ListProps) {
  const executable = status?.mode === 'execute' && status.runtime_available
  return <div className="space-y-3">
    {status ? <p role="status" className="text-xs text-slate-400">
      {MODES[status.mode]}{!status.runtime_available ? ' · 执行服务尚未启用' : ''}
    </p> : null}
    {schedules.length === 0 ? <p className="text-sm text-slate-400">尚未创建自动巡检。</p> : null}
    {schedules.map((schedule) => {
      const valid = schedule.validation_state === 'valid'
      return <article key={schedule.id} className="rounded-lg border border-white/[0.08] p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="break-words text-sm font-medium text-slate-100">{schedule.title}</h3>
            <p className="mt-1 break-words text-xs text-slate-400">
              {schedule.template_id ? TEMPLATES[schedule.template_id] : '历史定时配置'} · {schedule.schedule} · {schedule.timezone}
            </p>
            {schedule.on_project_changes ? <p className="mt-1 text-xs text-slate-400">同时巡检任务与审核变化 · 连续变化合并 · 至少间隔五分钟</p> : null}
            <p className="mt-1 text-xs text-slate-400">
              下一次：{time(schedule.next_run_at, schedule.timezone)} · {schedule.owner_user_id === userId ? '我的 Agent 执行' : '配置 owner 的 Agent 执行'}
            </p>
          </div>
          <Badge tone={schedule.blocked_reason || !valid ? 'remind' : 'neutral'}>
            {!valid ? '需要重新绑定项目与模板' : !schedule.enabled ? '已暂停' : schedule.blocked_reason ? '执行受阻' : '配置已启用'}
          </Badge>
        </div>
        {schedule.blocked_reason || schedule.last_error_code ? <p className="mt-2 text-xs text-rose">
          {taskManagementErrorMessage(new Error(schedule.blocked_reason ?? schedule.last_error_code ?? '执行失败'))}
        </p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onEdit(schedule)}>{valid ? '编辑' : '重新绑定'}</Button>
          <Button size="sm" variant="subtle" disabled={busy || !valid} onClick={() => onToggle(schedule)}>{schedule.enabled ? '暂停' : '恢复'}</Button>
          <Button size="sm" variant="subtle" disabled={busy || !valid || !executable} onClick={() => onRun(schedule)}>立即巡检</Button>
          <Button size="sm" variant="ghost" disabled={!valid} onClick={() => onHistory(schedule)}>运行记录</Button>
        </div>
      </article>
    })}
  </div>
}

export function AutomationSchedulePanel({ context }: { context: QueryScope }) {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [historyId, setHistoryId] = useState<string | null>(null)
  const [historyPage, setHistoryPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<InspectionSchedule | null>(null)
  const [title, setTitle] = useState('每日项目进展')
  const [cron, setCron] = useState('30 9 * * *')
  const [timezone, setTimezone] = useState('Asia/Shanghai')
  const [template, setTemplate] = useState<InspectionTemplate | ''>('daily_progress')
  const [onChanges, setOnChanges] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const commands = useRef(new Map<string, string>())
  const root = [...queryKeys.tasks.root, 'automation', context.userId, context.workspaceId, context.projectId] as const
  const status = useQuery({ queryKey: [...root, 'status'], queryFn: automationApi.status, refetchInterval: 10_000 })
  const definitions = useQuery({
    queryKey: [...root, 'definitions', page], queryFn: () => automationApi.list(context.projectId, page), refetchInterval: 10_000,
  })
  const history = useQuery({
    queryKey: [...root, 'history', historyId, historyPage], queryFn: () => automationApi.runs(historyId!, historyPage),
    enabled: historyId !== null, refetchInterval: historyId ? 5_000 : false,
  })
  const runId = searchParams.get('inspection')
  const report = useQuery({
    queryKey: [...root, 'report', runId], queryFn: () => automationApi.report(runId!), enabled: Boolean(runId), retry: false,
  })
  const commandId = (key: string) => {
    let id = commands.current.get(key)
    if (!id) { id = crypto.randomUUID(); commands.current.set(key, id) }
    return id
  }
  const refresh = async () => {
    await queryClient.cancelQueries({ queryKey: root })
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: root }),
      queryClient.invalidateQueries({ queryKey: queryKeys.inbox.root }),
    ])
  }
  const create = useMutation({
    mutationFn: () => {
      if (!template) throw new Error('请选择巡检模板。')
      const payload = {
        title, schedule: cron, timezone, template_id: template, project_id: context.projectId,
        enabled: true, on_project_changes: onChanges,
      }
      if (editing) return automationApi.update(editing.id, {
        ...payload, enabled: editing.enabled ?? true,
        command_id: commandId(JSON.stringify([editing.id, editing.version, payload])), expected_version: editing.version ?? 1,
      })
      return automationApi.create({ ...payload, command_id: commandId(JSON.stringify(payload)) })
    },
    onSuccess: async (schedule) => {
      setFormOpen(false); setEditing(null); setNotice('巡检配置已保存，执行由页面显示的自动执行模式控制。')
      setHistoryId(schedule.id); setHistoryPage(1); commands.current.clear(); await refresh()
    },
  })
  const toggle = useMutation({
    mutationFn: (schedule: InspectionSchedule) => automationApi.update(schedule.id, {
      command_id: commandId(`toggle:${schedule.id}:${schedule.version}`),
      expected_version: schedule.version ?? 1, enabled: !schedule.enabled,
    }),
    onSuccess: async () => { setNotice('巡检配置已更新。'); await refresh() },
  })
  const run = useMutation({
    mutationFn: (schedule: InspectionSchedule) => automationApi.runNow(
      schedule.id, commandId(`run:${schedule.id}:${schedule.version}`), schedule.version ?? 1,
    ),
    onSuccess: async (occurrence) => {
      commands.current.delete(`run:${occurrence.schedule_id}:${occurrence.definition_version}`)
      setHistoryId(occurrence.schedule_id); setHistoryPage(1)
      setNotice(occurrence.admission === 'admitted' ? '巡检已提交，完成后可在运行记录查看报告。'
        : occurrence.admission === 'skipped' ? '上一轮仍在运行，本次已记录为跳过。' : '执行条件未满足，请查看运行记录。')
      await refresh()
    },
  })
  const busy = create.isPending || toggle.isPending || run.isPending
  const error = create.error || toggle.error || run.error || definitions.error || status.error || history.error
  const openReport = (item: InspectionRun) => {
    if (!item.occurrence.run_id) return
    const next = new URLSearchParams(searchParams)
    next.set('inspection', item.occurrence.run_id); setSearchParams(next)
  }
  return <section aria-label="自动巡检" className="rounded-soft border border-white/[0.08] bg-surface-2 p-4">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-sm font-semibold text-slate-100">自动巡检</h2>
        <p className="mt-1 text-xs text-slate-400">定期核对任务与审核，发现变化时发送 Inbox 提醒。完整报告仅配置 owner 可见。</p></div>
      <Button size="sm" variant="subtle" onClick={() => {
        setEditing(null); setTemplate('daily_progress'); setCron('30 9 * * *'); setTimezone('Asia/Shanghai')
        setOnChanges(false)
        setTitle('每日项目进展'); setFormOpen(!formOpen)
      }}>新增巡检</Button>
    </div>
    {error ? <p role="alert" className="mb-3 text-sm text-rose">{taskManagementErrorMessage(error)}</p> : null}
    {notice ? <p role="status" className="mb-3 text-sm text-mint-300">{notice}</p> : null}
    {formOpen ? <form className="mb-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate() }}>
      <label className="text-xs text-slate-400">名称<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} className={FIELD} /></label>
      <label className="text-xs text-slate-400">巡检模板<select value={template} onChange={(event) => setTemplate(event.target.value as InspectionTemplate)} className={FIELD}>
        <option value="" disabled>请选择模板</option>
        {Object.entries(TEMPLATES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label className="text-xs text-slate-400">五段 cron<input required value={cron} onChange={(event) => setCron(event.target.value)} className={FIELD} /></label>
      <label className="text-xs text-slate-400">时区<input required value={timezone} onChange={(event) => setTimezone(event.target.value)} className={FIELD} /></label>
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={onChanges} onChange={(event) => setOnChanges(event.target.checked)} />任务或审核更新时也巡检
      </label>
      <p className="text-xs text-slate-400">连续变化会合并，自动巡检至少间隔五分钟；暂停期间的变化不补跑。</p>
      <p className="text-xs text-slate-400 sm:col-span-2">默认每天 09:30；最短间隔 5 分钟。单轮上限：8 次模型调用、12 次工具调用、32k tokens、10 分钟。当前三个模板直接查询记录，模型用量为 0。</p>
      {editing && editing.validation_state !== 'valid' ? <p className="text-xs text-remind sm:col-span-2">保存后将绑定到当前项目，使用创建者当前的个人 Agent 执行。</p> : null}
      <Button size="sm" type="submit" loading={create.isPending} disabled={busy || !template}>保存巡检</Button>
    </form> : null}
    {definitions.isLoading ? <p role="status" className="text-sm text-slate-400">正在读取巡检配置…</p> : <AutomationScheduleList
      schedules={definitions.data?.items ?? []} status={status.data} userId={context.userId} busy={busy}
      onToggle={(item) => toggle.mutate(item)} onRun={(item) => run.mutate(item)}
      onHistory={(item) => { setHistoryId(item.id); setHistoryPage(1) }}
      onEdit={(item) => {
        setEditing(item); setTitle(item.title); setTemplate(item.template_id ?? '')
        setOnChanges(item.on_project_changes ?? false)
        setCron(item.validation_state === 'valid' ? item.schedule : '30 9 * * *')
        setTimezone(item.timezone ?? 'Asia/Shanghai'); setFormOpen(true)
      }}
    />}
    <Pager page={page} total={definitions.data?.total_count ?? 0} onPage={setPage} />
    {historyId ? <div className="mt-4 border-t border-white/10 pt-3">
      <h3 className="mb-2 text-sm font-medium text-slate-200">运行记录</h3>
      {history.isLoading ? <p role="status" className="text-xs text-slate-400">正在读取运行记录…</p> : null}
      {history.data?.items.length === 0 ? <p className="text-xs text-slate-400">尚无运行记录。</p> : null}
      <ul className="space-y-2">{history.data?.items.map((item) => <li key={item.occurrence.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white/[0.03] p-3 text-xs text-slate-400">
        <div><p>{time(item.occurrence.scheduled_at)} · {item.occurrence.trigger === 'manual' ? '手动运行' : item.occurrence.trigger === 'change' ? '变更触发' : '定时运行'} · {RUN_STATES[item.status ?? item.occurrence.admission] ?? '等待执行'}</p>
          <p className="mt-1">工具 {item.tool_call_count ?? 0}/{item.occurrence.budget.max_tool_calls ?? 12} · 模型 {item.usage?.model_turns ?? 0} 次 · {item.usage?.total_tokens ?? 0} tokens</p>
          {item.error_code || item.occurrence.reason ? <p className="mt-1 text-rose">{taskManagementErrorMessage(new Error(item.error_code ?? item.occurrence.reason ?? '执行失败'))}</p> : null}
        </div>
        {item.status === 'completed' && item.occurrence.owner_user_id === context.userId ? <Button size="sm" variant="subtle" onClick={() => openReport(item)}>查看报告</Button> : null}
      </li>)}</ul>
      <Pager page={historyPage} total={history.data?.total_count ?? 0} onPage={setHistoryPage} />
    </div> : null}
    {runId ? <div className="mt-4"><ProjectInspectionView report={report.data} loading={report.isLoading}
      error={report.error ? taskManagementErrorMessage(report.error) : null} /></div> : null}
  </section>
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (page: number) => void }) {
  if (total <= 10) return null
  return <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
    <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</Button>
    <span>第 {page} 页 · 共 {total} 条</span>
    <Button size="sm" variant="ghost" disabled={page * 10 >= total} onClick={() => onPage(page + 1)}>下一页</Button>
  </div>
}
