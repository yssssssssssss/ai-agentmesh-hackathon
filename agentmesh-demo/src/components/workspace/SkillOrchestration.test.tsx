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
    skill_content_hash: 'hash',
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
        explicit_skill_names: [],
        complexity: 'assisted',
      },
      candidate_skill_ids: [skill.id],
      output_contract: ['feasibility_review'],
      preferred_order: [skill.id],
      nodes: [node(status)],
    },
    results: [],
    synthesis: null,
  }
}

describe('Skill orchestration views', () => {
  it.each([
    ['pending', '等待'],
    ['ready', '可执行'],
    ['running', '运行中'],
    ['waiting_tool_approval', '等待工具审批'],
    ['completed', '完成'],
    ['failed', '失败'],
    ['skipped', '已跳过'],
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
    expect(html).toContain('等待工具审批')
    expect(html).toContain('处理工具审批')
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
        onOpenSource={vi.fn()}
        onOpenArtifact={vi.fn()}
      />,
    )
    expect(html).toContain('Partial，部分节点降级')
    expect(html).toContain('PRD 可行性评估')
    expect(html).toContain('PRD v4')
    expect(html).toContain('未完成可用性测试')
    expect(html).toContain('artifact-1')
  })
})
