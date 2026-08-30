import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type {
  AgentRun,
  Skill,
  SkillNodeResult,
  SkillPlanDetailResponse,
  SkillPlanNode,
  SkillSynthesisResult,
} from '../../features/workspace/types'
import { SkillPlanNodeCard } from './SkillPlanNodeCard'
import { SkillPlanningState } from './SkillPlanningState'
import { SkillPlanPreview } from './SkillPlanPreview'
import { SkillPlanProgress } from './SkillPlanProgress'
import { SkillSynthesisView } from './SkillSynthesisView'

const skill: Skill = {
  id: 'skill-1',
  command: '$prd-feasibility',
  title: 'PRD 可行性评估',
  description: '评估 PRD',
  usage: '$prd-feasibility <input>',
  placeholder: '输入 PRD',
  aliases: [],
  requires_input: true,
  source: 'builtin',
  version: '1',
  activation_policy: 'explicit_only',
  enabled: true,
  binding_enabled: true,
  planner_eligible: true,
  readiness: 'ready',
  execution_readiness: 'complete',
  missing_tools: [],
  primary_stage: 'pre_design',
  capability_type: 'review',
  input_kinds: ['prd'],
  output_kinds: ['feasibility_review'],
  side_effect: 'read',
}

const candidateSkill: Skill = {
  ...skill,
  id: 'skill-2',
  command: '$generate-interview-guide',
  title: '用户访谈提纲',
  description: '根据研究目标生成访谈问题',
  usage: '$generate-interview-guide <input>',
  output_kinds: ['interview_guide'],
}

function node(status: SkillPlanNode['status'] = 'pending'): SkillPlanNode {
  return {
    id: 'node-1',
    skill_id: skill.id,
    skill_version: '1',
    reason: '先确认需求是否可落地',
    required: true,
    depends_on: [],
    input_bindings: ['user.prd'],
    output_contract: ['feasibility_review'],
    side_effect: 'read',
    status,
    attempt: status === 'pending' ? 0 : 1,
  }
}

function detail(status: SkillPlanNode['status'] = 'pending'): SkillPlanDetailResponse {
  return {
    plan: {
      id: 'plan-1',
      run_id: 'run-1',
      version: 3,
      status: status === 'pending' ? 'waiting_approval' : 'running',
      intent: {
        goal: '评估 PRD 并形成上线建议',
        primary_stage: 'pre_design',
        input_kinds: ['prd'],
        deliverables: ['feasibility_review'],
        constraints: { external_write: false, project_scope: 'current' },
        external_evidence_required: false,
        explicit_skill_names: [],
        complexity: 'assisted',
      },
      candidate_skill_ids: [skill.id],
      output_contract: ['feasibility_review'],
      preferred_order: [skill.id],
      nodes: [node(status)],
      planning_mode: 'standard',
      report_revision_count: 0,
      finalization_stage: 'none',
      finalization_version: 0,
    },
    results: [],
    synthesis: null,
  }
}

describe('Skill orchestration views', () => {
  it.each([
    ['pending', '等待开始'],
    ['ready', '即将开始'],
    ['running', '正在分析'],
    ['waiting_tool_approval', '等待高风险操作确认'],
    ['completed', '已完成'],
    ['failed', '执行失败'],
    ['skipped', '未执行'],
    ['cancelled', '已取消'],
  ] as const)('renders %s node status', (status, label) => {
    const html = renderToStaticMarkup(
      <SkillPlanNodeCard node={node(status)} skill={skill} mode="progress" />,
    )
    expect(html).toContain(label)
    expect(html).toContain('必需节点')
  })

  it('shows versioned preview without implying tool approval', () => {
    const preview = detail()
    preview.plan.candidate_skill_ids = [skill.id, candidateSkill.id]
    const html = renderToStaticMarkup(
      <SkillPlanPreview
        detail={preview}
        candidates={[skill, candidateSkill]}
        orchestrationMode="preview"
        pendingAction={null}
        error={null}
        onUpdate={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    )
    expect(html).toContain('Skill plan · v3')
    expect(html).toContain('尚未执行任何节点')
    expect(html).toContain('确认计划不会批准任何写入工具')
    expect(html).toContain('确认计划，仅预览')
    expect(html).toContain('可添加候选')
    expect(html).toContain('用户访谈提纲')
    expect(html).toContain('加入计划')
  })

  it('shows Task, Scenario, evidence, and capability gaps in route plans', () => {
    const preview = detail()
    preview.plan.routing_result = {
      catalog_version: 'user-research-v1',
      catalog_hash: 'a'.repeat(64),
      task: {
        task_id: 'define-strategy',
        confidence: 'high',
        reason: '最终交付需要形成策略和优先级',
        secondary_tasks: ['find-direction', 'understand-users'],
        execution_relation: 'parallel_then_merge',
      },
      scenario: {
        scenario_id: 'priority-roadmap',
        confidence: 'high',
        supporting_scenarios: ['competitor-benchmark-research', 'user-journey-insight'],
      },
      skill_routing: {
        planned_skills: ['planned-opportunity-evaluation-skill'],
        execution_mode: 'parallel_then_merge',
      },
      evidence_requirement: {
        external_evidence_required: true,
        minimum_sources: 5,
        independent_sources: 3,
      },
    }
    const routedNode = preview.plan.nodes?.[0]
    if (!routedNode) throw new Error('expected a plan node')
    preview.plan.nodes = [{
      ...routedNode,
      scenario_id: 'competitor-benchmark-research',
      skill_status: 'draft',
      required_tool_names: ['web_research'],
      knowledge_bindings: { required: ['method-one'], optional: [], excluded: [] },
      completion_criteria: ['结论有来源'],
    }]

    const html = renderToStaticMarkup(
      <SkillPlanPreview
        detail={preview}
        candidates={[skill]}
        orchestrationMode="preview"
        pendingAction={null}
        error={null}
        onUpdate={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    )

    expect(html).toContain('define-strategy')
    expect(html).toContain('priority-roadmap')
    expect(html).toContain('需要外部证据')
    expect(html).toContain('候选能力尚未接入')
    expect(html).toContain('web_research')
    expect(html).toContain('完成标准：结论有来源')
  })

  it('requires explicit assignment when a selected Skill matches multiple scenarios', () => {
    const preview = detail()
    preview.scenario_assignment_options = {
      [skill.id]: [
        {
          scenario_id: 'scenario-one',
          title: '场景一',
          output_ids: ['analysis_result'],
          output_labels: ['分析结论'],
        },
        {
          scenario_id: 'scenario-two',
          title: '场景二',
          output_ids: ['analysis_result'],
          output_labels: ['对比结论'],
        },
      ],
    }

    const html = renderToStaticMarkup(
      <SkillPlanPreview
        detail={preview}
        candidates={[skill]}
        orchestrationMode="execute"
        pendingAction={null}
        error={null}
        onUpdate={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    )

    expect(html).toContain('确认场景归属')
    expect(html).toContain('场景一')
    expect(html).toContain('场景二')
    expect(html).toContain('请选择所有多义节点的场景归属')
    const approval = html.match(/<button([^>]*)>确认并开始执行<\/button>/)
    expect(approval?.[1] ?? '').toMatch(/\sdisabled(?:=|$)/)
  })

  it('allows approving a DeepSearch plan that retains blocking capability gaps', () => {
    const preview = detail()
    preview.plan.capability_gaps = ['deliverable:unavailable_output']

    const html = renderToStaticMarkup(
      <SkillPlanPreview
        detail={preview}
        candidates={[skill]}
        orchestrationMode="execute"
        pendingAction={null}
        error={null}
        onUpdate={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    )

    expect(html).toContain('能力缺口')
    const approval = html.match(/<button([^>]*)>确认并开始执行<\/button>/)
    expect(approval?.[1] ?? '').not.toMatch(/\sdisabled(?:=|$)/)
  })

  it('moves preview controls below node content on narrow screens', () => {
    const html = renderToStaticMarkup(
      <SkillPlanNodeCard
        node={node()}
        skill={skill}
        mode="preview"
        canMoveDown
        onToggle={vi.fn()}
        onMove={vi.fn()}
        onSelectOnly={vi.fn()}
      />,
    )

    expect(html).toContain('grid-cols-[auto_minmax(0,1fr)]')
    expect(html).toContain('sm:grid-cols-[auto_minmax(0,1fr)_auto]')
    expect(html).toContain('col-span-2')
    expect(html).toContain('sm:col-span-1')
    expect(html).toContain('仅此项')
  })

  it('keeps tool approval distinct in progress', () => {
    const run = {
      id: 'run-1',
      thread_id: 'thread-1',
      user_id: 'user-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      input_text: '评估 PRD',
      status: 'waiting_approval',
      planning_mode: 'standard',
      orchestration_version: 'v1',
      orchestration_mode: 'execute',
      agent_definition_version: '1',
      project_chat: true,
      tool_call_count: 1,
    } satisfies AgentRun
    const html = renderToStaticMarkup(
      <SkillPlanProgress
        run={run}
        detail={detail('waiting_tool_approval')}
        skillsById={new Map([[skill.id, skill]])}
        cancelling={false}
        onCancel={vi.fn()}
        onOpenToolApproval={vi.fn()}
      />,
    )
    expect(html).toContain('需要确认高风险操作')
    expect(html).toContain('为什么这次仍需要确认？')
    expect(html).toContain('常规只读工具会直接继承')
    expect(html).toContain('查看高风险操作')
  })

  it('shows verifiable planning stages instead of a static technical status', () => {
    const run = {
      id: 'run-planning',
      thread_id: 'thread-1',
      user_id: 'user-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      input_text: '分析竞品并形成策略',
      status: 'planning',
      planning_mode: 'standard',
      orchestration_version: 'v1',
      orchestration_mode: 'execute',
      agent_definition_version: '1',
      project_chat: true,
      tool_call_count: 0,
    } satisfies AgentRun

    const html = renderToStaticMarkup(
      <SkillPlanningState run={run} cancelling={false} onCancel={vi.fn()} />,
    )

    expect(html).toContain('正在构建执行计划')
    expect(html).toContain('匹配任务场景')
    expect(html).toContain('检查能力与权限')
    expect(html).toContain('此阶段不会调用外部工具')
    expect(html).toContain('planning-scan')
    expect(html).not.toContain('状态：planning')
  })

  it('explains parallel execution as steps in one plan', () => {
    const progress = detail('running')
    const first = progress.plan.nodes?.[0]
    if (!first) throw new Error('expected a plan node')
    progress.plan.routing_result = {
      catalog_version: 'user-research-v1',
      catalog_hash: 'a'.repeat(64),
      task: {
        task_id: 'define-strategy',
        confidence: 'high',
        reason: '需要合并多类分析',
        secondary_tasks: [],
        execution_relation: 'parallel_then_merge',
      },
      scenario: {
        scenario_id: 'strategy-synthesis',
        confidence: 'high',
        supporting_scenarios: ['competitor-benchmark-research'],
      },
      skill_routing: { planned_skills: [], execution_mode: 'parallel_then_merge' },
      evidence_requirement: { external_evidence_required: false, minimum_sources: 0, independent_sources: 0 },
    }
    progress.plan.nodes = [
      { ...first, id: 'node-1', parallel_group: 'analysis' },
      { ...first, id: 'node-2', skill_id: candidateSkill.id, parallel_group: 'analysis' },
    ]
    const run = {
      id: 'run-1', thread_id: 'thread-1', user_id: 'user-1', workspace_id: 'workspace-1', project_id: 'project-1',
      input_text: '并行分析', status: 'running', planning_mode: 'standard', orchestration_version: 'v1', orchestration_mode: 'execute',
      agent_definition_version: '1', project_chat: true, tool_call_count: 0,
    } satisfies AgentRun

    const html = renderToStaticMarkup(
      <SkillPlanProgress
        run={run}
        detail={progress}
        skillsById={new Map([[skill.id, skill], [candidateSkill.id, candidateSkill]])}
        cancelling={false}
        onCancel={vi.fn()}
        onOpenToolApproval={vi.fn()}
      />,
    )

    expect(html).toContain('正在同时处理 2 个分析步骤')
    expect(html).toContain('不是多套方案')
    expect(html).toContain('完成后会合并为一份结果')
    expect(html.match(/可与其他步骤并行/g)).toHaveLength(2)
  })

  it('explains provider disconnects and the automatic retry policy before technical codes', () => {
    const failedDetail = detail('failed')
    const failedNode = failedDetail.plan.nodes?.[0]
    if (!failedNode) throw new Error('expected a plan node')
    failedNode.error_code = 'RemoteProtocolError'
    failedNode.attempt = 2
    const html = renderToStaticMarkup(
      <SkillPlanNodeCard node={failedNode} skill={skill} mode="progress" />,
    )

    expect(html).toContain('外部模型服务在返回完整内容前断开')
    expect(html).toContain('不是你的需求有问题')
    expect(html).toContain('应用层最多进行 3 次模型请求')
    expect(html).toContain('查看技术原因')
  })

  it('explains a stream that ended without a completion event', () => {
    const failedNode = node('failed')
    failedNode.error_code = 'ModelStreamIncompleteError'
    const html = renderToStaticMarkup(
      <SkillPlanNodeCard node={failedNode} skill={skill} mode="progress" />,
    )

    expect(html).toContain('提前结束响应')
    expect(html).toContain('应用层最多进行 3 次模型请求')
  })

  it('shows the failed required node as the cause of an unsatisfied run contract', () => {
    const failedDetail = detail('failed')
    const failedNode = failedDetail.plan.nodes?.[0]
    if (!failedNode) throw new Error('expected a plan node')
    failedNode.error_code = 'RemoteProtocolError'
    failedNode.attempt = 1
    const run = {
      id: 'run-1', thread_id: 'thread-1', user_id: 'user-1', workspace_id: 'workspace-1', project_id: 'project-1',
      input_text: '分析竞品', status: 'failed', error_code: 'output_contract_unsatisfied', planning_mode: 'standard',
      orchestration_version: 'v1', orchestration_mode: 'execute', agent_definition_version: '1', project_chat: true,
      tool_call_count: 1,
    } satisfies AgentRun

    const html = renderToStaticMarkup(
      <SkillPlanProgress
        run={run}
        detail={failedDetail}
        skillsById={new Map([[skill.id, skill]])}
        cancelling={false}
        onCancel={vi.fn()}
        onOpenToolApproval={vi.fn()}
      />,
    )

    expect(html).toContain('外部模型服务在返回完整内容前断开')
    expect(html).toContain('因此没有覆盖计划要求的交付内容')
    expect(html).toContain('RemoteProtocolError')
    expect(html).toContain('output_contract_unsatisfied')
  })

  it('translates machine degradation diagnostics into a scope explanation', () => {
    const progress = detail('running')
    progress.plan.degradation = 'capability_gaps:required_knowledge_metadata_only:scenario-a:knowledge-a'
    const run = {
      id: 'run-1', thread_id: 'thread-1', user_id: 'user-1', workspace_id: 'workspace-1', project_id: 'project-1',
      input_text: '分析', status: 'running', planning_mode: 'standard', orchestration_version: 'v1', orchestration_mode: 'execute',
      agent_definition_version: '1', project_chat: true, tool_call_count: 0,
    } satisfies AgentRun

    const html = renderToStaticMarkup(
      <SkillPlanProgress
        run={run}
        detail={progress}
        skillsById={new Map([[skill.id, skill]])}
        cancelling={false}
        onCancel={vi.fn()}
        onOpenToolApproval={vi.fn()}
      />,
    )

    expect(html).toContain('部分知识资料不可直接读取')
    expect(html).toContain('不能作为证据')
    expect(html).toContain('查看技术诊断')
  })

  it('labels an approved preview as unexecuted instead of completed work', () => {
    const preview = detail()
    preview.plan.status = 'approved'
    const run = {
      id: 'run-1',
      thread_id: 'thread-1',
      user_id: 'user-1',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      input_text: '评估 PRD',
      status: 'completed',
      planning_mode: 'standard',
      plan_id: preview.plan.id,
      orchestration_version: 'v1',
      orchestration_mode: 'preview',
      agent_definition_version: '1',
      project_chat: true,
      tool_call_count: 0,
    } satisfies AgentRun

    const html = renderToStaticMarkup(
      <SkillPlanProgress
        run={run}
        detail={preview}
        skillsById={new Map([[skill.id, skill]])}
        cancelling={false}
        onCancel={vi.fn()}
        onOpenToolApproval={vi.fn()}
      />,
    )

    expect(html).toContain('计划已确认，预览模式未执行')
  })

  it('renders claim lineage, sources, limitations, and partial state', () => {
    const result = {
      id: 'result-1',
      node_id: 'node-1',
      skill_id: skill.id,
      summary: 'PRD 存在关键依赖',
      sources: [{ id: 'source-1', title: 'PRD v4', source_type: 'document', reference: 'doc-1' }],
      confidence: 0.8,
      usage: { total_tokens: 42 },
      attempt: 1,
    } as SkillNodeResult
    const synthesis = {
      summary: '建议先解决关键依赖',
      sections: ['需求依据'],
      claims: [{
        text: '当前版本不宜直接上线',
        node_result_ids: ['result-1'],
        source_ids: ['source-1'],
        recommendation: false,
      }],
      limitations: ['未完成可用性测试'],
      next_actions: ['补齐依赖'],
      artifact_ids: ['artifact-1'],
    } satisfies SkillSynthesisResult
    const html = renderToStaticMarkup(
      <SkillSynthesisView
        synthesis={synthesis}
        results={[result]}
        skillsById={new Map([[skill.id, skill]])}
        partial
        completionCheck={{
          completed: false,
          evidence_sufficient: false,
          confidence: 'medium',
          human_confirmation_required: false,
          reason: '自动检查 Scenario 节点、输出血缘和外部证据覆盖。',
          gaps: ['external_evidence_insufficient:sources=3/5,independent=3/3'],
        }}
        onOpenSource={vi.fn()}
        onOpenArtifact={vi.fn()}
      />,
    )
    expect(html).toContain('部分完成，有未满足项')
    expect(html).toContain('为什么是“部分完成”？')
    expect(html).toContain('外部来源 3/5，独立来源 3/3')
    expect(html).toContain('PRD 可行性评估')
    expect(html).toContain('PRD v4')
    expect(html).toContain('未完成可用性测试')
    expect(html).toContain('artifact-1')
  })

  it('renders synthesis summary and sections as Markdown', () => {
    const synthesis = {
      summary: '**核心结论**：优先验证任务入口。',
      sections: ['## 竞品分析\n\n### 关键发现\n\n- **第一项**\n- 第二项'],
      claims: [],
      limitations: [],
      next_actions: [],
      artifact_ids: [],
    } satisfies SkillSynthesisResult

    const html = renderToStaticMarkup(
      <SkillSynthesisView
        synthesis={synthesis}
        results={[]}
        skillsById={new Map()}
        reportRunId="run/report 1"
        onOpenSource={vi.fn()}
        onOpenArtifact={vi.fn()}
      />,
    )

    expect(html).toContain('<strong>核心结论</strong>')
    expect(html).toContain('>竞品分析</h2>')
    expect(html).toContain('>关键发现</h3>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<strong>第一项</strong>')
    expect(html).not.toContain('## 竞品分析')
    expect(html).not.toContain('**第一项**')
    expect(html).toContain('/api/agent/runs/run%2Freport%201/report.html')
    expect(html).toContain('独立查看')
    expect(html).toContain('下载 HTML')
  })
})
