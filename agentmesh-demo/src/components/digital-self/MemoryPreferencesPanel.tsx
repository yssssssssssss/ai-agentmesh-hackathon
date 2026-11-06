import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { learningApi, learningError, type MemoryPreferences } from '../../features/knowledge/learningApi'
import { Button } from '../ui/Button'

export function MemoryPreferencesPanel({ userId }: { userId: string }) {
  const client = useQueryClient()
  const key = ['memory-learning', userId]
  const preferences = useQuery({ queryKey: [...key, 'preferences'], queryFn: learningApi.preferences })
  const status = useQuery({ queryKey: [...key, 'status'], queryFn: learningApi.status })
  const save = useMutation({ mutationFn: learningApi.patchPreferences,
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: key }), client.invalidateQueries({ queryKey: ['memory'] })]),
  })
  return <section className="card-base p-5" aria-label="我的记忆设置">
    <h2 className="text-base font-semibold text-slate-100">我的记忆设置</h2>
    <p className="mt-1 text-xs text-slate-400">核心偏好和资料学习策略仅属于本人。资料产生的推断需要逐条确认，普通聊天不会自动共享。</p>
    {preferences.isLoading ? <p className="mt-3 text-sm text-slate-400">正在读取设置…</p> : null}
    {preferences.error ? <p role="alert" className="mt-3 text-sm text-rose">无法读取记忆设置。</p> : null}
    {preferences.data ? <MemoryPreferencesForm key={preferences.data.version} preferences={preferences.data}
      executable={status.data?.mode === 'execute'} pending={save.isPending}
      onSave={(payload) => save.mutate({ ...payload, command_id: crypto.randomUUID(), expected_version: preferences.data!.version })} /> : null}
    {save.error ? <p role="alert" className="mt-2 text-sm text-rose">{learningError(save.error)}</p> : null}
    {save.isSuccess ? <p role="status" className="mt-2 text-xs text-mint-300">记忆设置已保存。</p> : null}
  </section>
}

export function MemoryPreferencesForm({ preferences, executable, pending, onSave }: {
  preferences: MemoryPreferences
  executable: boolean
  pending: boolean
  onSave: (payload: { learning_enabled: boolean; core_preferences: string[]; daily_token_cap: number }) => void
}) {
  const [enabled, setEnabled] = useState(preferences.learning_enabled)
  const [text, setText] = useState((preferences.core_preferences ?? []).join('\n'))
  const [budget, setBudget] = useState(preferences.daily_token_cap)
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean)
  const valid = lines.length <= 8 && lines.every((line) => line.length <= 400) && budget >= 4000 && budget <= 200000
  return <form className="mt-4 space-y-3" onSubmit={(event) => {
    event.preventDefault()
    if (valid) onSave({ learning_enabled: enabled, core_preferences: lines, daily_token_cap: budget })
  }}>
    <label className="flex items-center gap-2 text-sm text-slate-200">
      <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={pending} />
      允许从我的授权资料生成私有候选记忆
    </label>
    {!executable ? <p className="text-xs text-amber-300">后台资料学习尚未启用；核心偏好可以独立保存。</p> : null}
    <label className="block text-sm text-slate-300">核心偏好（每行一条，最多 8 条）
      <textarea className="mt-1 min-h-24 w-full rounded-control border border-white/10 bg-surface-1 p-3 text-sm"
        value={text} maxLength={3208} onChange={(event) => setText(event.target.value)} disabled={pending} />
    </label>
    <p className="text-xs text-slate-400">偏好独立于资料学习开关；启用记忆上下文后应用于你的本地 Agent 对话。</p>
    <label className="block text-sm text-slate-300">每日后台学习预算（Token）
      <input type="number" min={4000} max={200000} step={1000} value={budget} disabled={pending}
        onChange={(event) => setBudget(Number(event.target.value))}
        className="ml-3 w-28 rounded-control border border-white/10 bg-surface-1 p-2" />
    </label>
    <p className="text-xs text-slate-400">后台学习使用独立预算。中断的尝试保留预算预留，避免重启后重复消耗。</p>
    {!valid ? <p role="alert" className="text-xs text-rose">请检查偏好条数、单条长度和预算范围。</p> : null}
    <Button type="submit" size="sm" loading={pending} disabled={!valid}>保存记忆设置</Button>
  </form>
}
