import type { PlanNodeView, SkillPlanNode } from '../../features/workspace/types'

const SKILL_STATUS_LABELS: Record<NonNullable<SkillPlanNode['skill_status']>, string> = {
  draft: '试运行 Skill',
  reviewed: '已评审 Skill',
  validated: '已验证 Skill',
}

const FAILURE_MESSAGES: Record<string, string> = {
  dependency_failed: '它依赖的前置步骤没有完成，因此系统没有继续使用不完整输入。',
  missing_node_result: '执行器结束后没有返回符合约定格式的结果。',
  planned_tool_grant_revoked: '执行所需的工具权限已被撤销。系统为避免越权调用而停止。',
  process_restarted: '服务在执行期间重启，中间状态无法安全恢复。',
  parent_run_deadline_exceeded: '整个任务已达到最长执行时间，系统停止了本步骤。',
  output_contract_unsatisfied: '已有结果没有覆盖计划要求的交付内容。',
  model_not_configured: '当前没有可用的模型配置。',
  ModelStreamIncompleteError: '外部模型服务提前结束响应，没有返回完整内容。这是传输故障，不是你的需求有问题。',
  RemoteProtocolError: '外部模型服务在返回完整内容前断开了连接。这是传输故障，不是你的需求有问题。',
  ReadError: '读取外部服务响应时连接中断。这是传输故障，不是你的需求有问题。',
  ConnectError: '系统未能连接到外部服务。这是服务连接问题，不是需求内容错误。',
  UserError: '执行器拒绝了不符合约束的工具参数或资源访问。这类名称来自 SDK，不表示用户的需求有错。',
  ValueError: '返回内容或执行输入没有通过结构校验，因此不能作为有效结果。',
  ModelTimeoutError: '模型在限定时间内没有返回结果。',
  ProviderTimeoutError: '外部服务在限定时间内没有返回结果。',
  TimeoutError: '本步骤超过了最长执行时间。',
  PermissionError: '当前账号没有执行此步骤所需的权限。',
}

export function skillStatusLabel(status: SkillPlanNode['skill_status']): string | null {
  return status ? SKILL_STATUS_LABELS[status] : null
}

export function nodeStatusDescription(node: PlanNodeView): string {
  if (node.status === 'pending') {
    return (node.depends_on ?? []).length > 0
      ? '等待前置步骤完成后自动开始。'
      : '已进入执行队列，等待系统分配。'
  }
  if (node.status === 'ready') return '运行条件已满足，即将开始处理。'
  if (node.status === 'running') {
    return (node.required_tool_names ?? []).length > 0
      ? '正在使用已获授权的工具与输入生成本步骤结果，尚未形成最终结论。'
      : '正在根据已确认的输入生成本步骤结果，尚未形成最终结论。'
  }
  if (node.status === 'waiting_tool_approval') {
    const tools = (node.required_tool_names ?? []).join('、')
    return tools
      ? `${tools} 的本次操作超出常规只读权限。系统已暂停，等待你确认具体影响范围。`
      : '本次操作涉及写入或命中高风险策略。系统已暂停，等待你确认具体影响范围。'
  }
  if (node.status === 'completed') return '结果已保存，将用于最终汇总。'
  if (node.status === 'failed') return failureReason(node.error_code)
  if (node.status === 'skipped') return '前置步骤未完成或该步骤已不再满足执行条件，因此没有运行。'
  return '任务已取消，本步骤不会继续运行。'
}

export function failureReason(errorCode: string | null | undefined): string {
  if (!errorCode) return '本步骤没有产出符合要求的结果。'
  if (FAILURE_MESSAGES[errorCode]) return FAILURE_MESSAGES[errorCode]
  const normalized = errorCode.toLowerCase()
  if (normalized.includes('timeout') || normalized.includes('deadline')) {
    return '本步骤在限定时间内没有返回可用结果。'
  }
  if (normalized.includes('permission') || normalized.includes('grant') || normalized.includes('auth')) {
    return '执行所需权限不可用。系统为避免越权调用而停止。'
  }
  if (normalized.includes('provider') || normalized.includes('connection') || normalized.includes('network')) {
    return '外部服务或网络连接异常，本步骤没有获得可验证结果。'
  }
  if (normalized.includes('schema') || normalized.includes('validation') || normalized.includes('contract')) {
    return '返回内容没有通过结构或完成条件校验，因此不能作为有效结果。'
  }
  return '本步骤发生技术异常，没有产出可验证结果。'
}

export function runFailurePresentation(
  errorCode: string,
  nodes: PlanNodeView[],
): { description: string; technicalCodes: string[] } {
  if (errorCode !== 'output_contract_unsatisfied') {
    return { description: failureReason(errorCode), technicalCodes: [errorCode] }
  }
  const failedNodes = nodes.filter((node) => node.status === 'failed' && node.error_code)
  const cause = failedNodes.find((node) => node.required) ?? failedNodes[0]
  if (!cause?.error_code) {
    return { description: failureReason(errorCode), technicalCodes: [errorCode] }
  }
  return {
    description: `${failureReason(cause.error_code)} 因此没有覆盖计划要求的交付内容。`,
    technicalCodes: [cause.error_code, errorCode],
  }
}

export function failurePolicy(errorCode: string | null | undefined, attempt: number): string {
  const attemptCopy = attempt > 1 ? `系统已执行 ${attempt} 次。` : ''
  const normalized = (errorCode ?? '').toLowerCase()
  if (normalized.includes('remoteprotocol') || normalized.includes('connection') || normalized.includes('network') || normalized.includes('readerror') || normalized.includes('streamincomplete')) {
    return '这类临时传输故障会在当前步骤内自动重试，应用层最多进行 3 次模型请求；如果仍然失败，可稍后以新 Run 重试，无需改写需求。'
  }
  if (normalized.includes('timeout') || normalized.includes('deadline')) {
    return `${attemptCopy}可以缩小单次任务范围后重试；系统不会在超时后继续占用外部服务。`
  }
  if (normalized.includes('permission') || normalized.includes('grant') || normalized.includes('auth')) {
    return `${attemptCopy}请在个人 Agent 设置中启用所需工具。权限一旦授予，只读 Skill 调用不会再次逐次询问。`
  }
  if (normalized.includes('schema') || normalized.includes('validation') || normalized.includes('contract') || errorCode === 'ValueError') {
    return `${attemptCopy}系统会保留原始输入，但不会接受不符合输出契约的结果；重试时会重新生成并校验。`
  }
  return `${attemptCopy}系统只自动重试只读或草稿类的临时连接故障，最多两次；其它错误会停止，避免重复调用或生成未经验证的结论。`
}

export function degradationCopy(value: string): { title: string; description: string } {
  const metadataOnlyCount = (value.match(/required_knowledge_metadata_only:/g) ?? []).length
  if (metadataOnlyCount > 0) {
    return {
      title: '部分知识资料不可直接读取',
      description: `${metadataOnlyCount} 项必需知识目前只有目录信息，不能作为证据。系统会继续处理可用步骤，但完成检查不会把缺失部分算作已满足。`,
    }
  }
  if (value.includes('external_evidence_insufficient:')) {
    const match = value.match(/sources=(\d+\/\d+),independent=(\d+\/\d+)/)
    return {
      title: '外部证据尚未达到完成标准',
      description: match
        ? `当前来源 ${match[1]}，独立来源 ${match[2]}。已有内容可以查看，但会标记为部分完成。`
        : '当前来源数量或独立性不足，已有内容可以查看，但会标记为部分完成。',
    }
  }
  if (value.includes('scenario_outputs_incomplete:') || value.includes('scenario_criterion_unmet:')) {
    return {
      title: '部分交付内容尚未通过完成检查',
      description: '系统保留已验证结果，并明确标记未覆盖的场景输出或完成标准，不会用推测补齐。',
    }
  }
  if (value.includes('runtime_skill_unbound:') || value.includes('capability_gaps:')) {
    return {
      title: '计划存在能力或资料缺口',
      description: '部分目标没有可执行能力或可读资料支撑。系统不会改用无工具回答，最终结果会明确标记缺口。',
    }
  }
  if (/\p{Script=Han}/u.test(value) && !value.includes('_')) {
    return {
      title: '结果范围受到限制',
      description: value,
    }
  }
  return {
    title: '结果范围受到限制',
    description: '系统检测到输入、能力或证据不完整，因此会保留限制说明，不会把未验证内容当作完整结论。',
  }
}

export function completionGapLabel(value: string): string {
  if (value.startsWith('external_evidence_insufficient:')) {
    const match = value.match(/sources=(\d+\/\d+),independent=(\d+\/\d+)/)
    return match
      ? `外部来源 ${match[1]}，独立来源 ${match[2]}，尚未达到计划要求`
      : '外部来源数量或独立性尚未达到计划要求'
  }
  if (value.startsWith('required_knowledge_metadata_only:')) return '必需知识只有目录信息，不能作为执行依据'
  if (value.startsWith('runtime_skill_unbound:')) return '目标场景尚未绑定可执行 Skill'
  if (value.startsWith('scenario_unexecuted:')) return '计划中的目标场景尚未执行'
  if (value.startsWith('scenario_outputs_incomplete:')) return '目标场景没有产出全部约定内容'
  if (value.startsWith('scenario_criterion_unmet:')) return '目标场景的完成标准尚未全部满足'
  if (value.startsWith('scenario_missing:')) return '运行时目录中缺少目标场景'
  return '有一项计划完成条件尚未满足'
}

export function capabilityGapLabel(value: string): string {
  if (value.startsWith('required_knowledge_metadata_only:')) return '必需知识只有目录信息'
  if (value.startsWith('runtime_skill_unbound:')) return '场景尚未绑定可执行 Skill'
  if (value.startsWith('scenario_unexecuted:')) return '场景尚未执行'
  if (value.startsWith('external_evidence_insufficient:')) return '外部证据不足'
  return '计划能力尚未满足'
}
