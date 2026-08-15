import { useEffect, useState } from 'react'
import { Bot, Save } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { useAgentAdmin, useAgentToolsAdmin } from './api'

interface AgentModuleProps {
  context: { userId: string; workspaceId: string }
}

function message(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '请求失败'
}

export function AgentModule({ context }: AgentModuleProps) {
  const resource = useAgentAdmin(context, true)
  const publicAgents = resource.agents.data?.items.filter((agent) => agent.agent_type !== 'personal') ?? []
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>([])
  const [initializedAgentId, setInitializedAgentId] = useState<string | null>(null)
  const agentTools = useAgentToolsAdmin(context, selectedAgentId, true)
  const selectedAgent = publicAgents.find((agent) => agent.id === selectedAgentId)

  useEffect(() => {
    if (selectedAgentId || publicAgents.length === 0) return
    setSelectedAgentId(publicAgents[0].id ?? null)
  }, [publicAgents, selectedAgentId])
  useEffect(() => {
    setInitializedAgentId(null)
  }, [selectedAgentId])
  useEffect(() => {
    if (!selectedAgentId || !agentTools.isSuccess) return
    setSelectedToolIds(agentTools.data.items.map((tool) => tool.id))
    setInitializedAgentId(selectedAgentId)
  }, [agentTools.data, agentTools.isSuccess, selectedAgentId])

  const toolGrantsUnavailable =
    !selectedAgentId ||
    initializedAgentId !== selectedAgentId ||
    agentTools.isFetching ||
    agentTools.isError ||
    resource.tools.isFetching ||
    resource.tools.isError

  const toggleTool = (toolId: string) => {
    setSelectedToolIds((current) => current.includes(toolId) ? current.filter((id) => id !== toolId) : [...current, toolId])
  }

  return (
    <Card padding="lg">
      <div>
        <h2 className="text-lg font-semibold text-white">Agent 配置</h2>
        <p className="mt-1 text-sm text-slate-500">查看公共 Agent 运行态并配置基础模型和工具。</p>
      </div>
      {resource.agents.isLoading ? <p className="mt-5 text-sm text-slate-500">正在加载 Agent…</p> : null}
      {resource.agents.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.agents.error)}</p> : null}
      {!resource.agents.isLoading && !resource.agents.isError && publicAgents.length === 0 ? <p className="mt-5 text-sm text-slate-500">当前没有可配置的公共 Agent。</p> : null}
      {publicAgents.length > 0 ? (
        <div className="mt-5 grid gap-5 lg:grid-cols-[280px_1fr]">
          <div className="space-y-2" role="list" aria-label="公共 Agent">
            {publicAgents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                onClick={() => setSelectedAgentId(agent.id ?? null)}
                className={`w-full rounded-[10px] border px-4 py-3 text-left transition-colors ${agent.id === selectedAgentId ? 'border-mint-400/35 bg-mint-400/[0.08]' : 'border-white/[0.06] bg-surface-2 hover:border-white/[0.12]'}`}
              >
                <span className="flex items-center gap-2 text-sm font-medium text-slate-100"><Bot className="h-4 w-4 text-mint-300" />{agent.name}</span>
                <span className="mt-2 flex gap-2"><Badge>{agent.status}</Badge><Badge>{agent.runtime_status}</Badge></span>
              </button>
            ))}
          </div>
          {selectedAgent ? (
            <div className="space-y-5 rounded-[12px] border border-white/[0.06] bg-surface-2 p-5">
              <div>
                <h3 className="text-base font-semibold text-white">{selectedAgent.name}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-400">{selectedAgent.description}</p>
                <p className="mt-2 text-xs text-slate-500">当前任务：{selectedAgent.current_task_title ?? '无'}</p>
              </div>
              <label className="block text-sm text-slate-300">
                模型
                <select
                  aria-label="Agent 模型"
                  value={selectedAgent.model_id ?? ''}
                  disabled={resource.models.isLoading || resource.updateModel.isPending}
                  onChange={(event) => resource.updateModel.mutate({ agentId: selectedAgent.id ?? '', modelId: event.target.value || null })}
                  className="mt-2 h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 text-white outline-none"
                >
                  <option value="">未配置</option>
                  {resource.models.data?.items.map((model) => <option key={model.id} value={model.id}>{model.label} · {model.provider}</option>)}
                </select>
              </label>
              <fieldset disabled={toolGrantsUnavailable || resource.updateTools.isPending}>
                <legend className="text-sm text-slate-300">工具</legend>
                {agentTools.isFetching || resource.tools.isFetching ? <p className="mt-2 text-sm text-slate-500">正在加载当前工具授权…</p> : null}
                {agentTools.isError ? <p role="alert" className="mt-2 text-sm text-rose">{message(agentTools.error)}</p> : null}
                {resource.tools.isError ? <p role="alert" className="mt-2 text-sm text-rose">{message(resource.tools.error)}</p> : null}
                {!agentTools.isFetching && !resource.tools.isFetching && !agentTools.isError && resource.tools.data && resource.tools.data.items.length > 0 ? (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    {resource.tools.data.items.map((tool) => (
                      <label key={tool.id} className="flex items-start gap-3 rounded-[10px] border border-white/[0.06] bg-surface-1 p-3 text-sm text-slate-300">
                        <input type="checkbox" checked={selectedToolIds.includes(tool.id)} onChange={() => toggleTool(tool.id)} className="mt-1 accent-emerald-400" />
                        <span><span className="block font-medium text-slate-100">{tool.name}</span><span className="mt-1 block text-xs text-slate-500">{tool.provider} · {tool.risk_level}</span></span>
                      </label>
                    ))}
                  </div>
                ) : null}
                {!agentTools.isFetching && !resource.tools.isFetching && !agentTools.isError && resource.tools.data?.items.length === 0 ? <p className="mt-2 text-sm text-slate-500">当前没有可用工具。</p> : null}
                <Button
                  className="mt-3"
                  variant="secondary"
                  icon={<Save className="h-4 w-4" />}
                  loading={resource.updateTools.isPending}
                  disabled={toolGrantsUnavailable}
                  onClick={() => {
                    if (!selectedAgent.id || initializedAgentId !== selectedAgent.id) return
                    resource.updateTools.mutate({ agentId: selectedAgent.id, toolIds: selectedToolIds })
                  }}
                >保存工具</Button>
              </fieldset>
              {resource.updateModel.isError ? <p role="alert" className="text-sm text-rose">{message(resource.updateModel.error)}</p> : null}
              {resource.updateTools.isError ? <p role="alert" className="text-sm text-rose">{message(resource.updateTools.error)}</p> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
