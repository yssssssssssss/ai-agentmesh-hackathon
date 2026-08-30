import { createHash } from 'node:crypto'

import { expect, type Page, type Route, test } from '@playwright/test'

import type { components } from '../src/api/generated/schema'
import type { DeepSearchReport } from '../src/features/deepsearch/types'
import { loginAs } from './support/auth'

const NOW = '2026-08-27T02:00:00Z'
const RUN_ID = 'run_deepsearch_e2e'
const THREAD_ID = 'thread_deepsearch_e2e'
const PLAN_ID = 'plan_deepsearch_e2e'

type AgentRun = components['schemas']['AgentRun']
type AgentRunCreateRequest = components['schemas']['AgentRunCreateRequest']
type AgentRunEvent = components['schemas']['AgentRunEvent']
type ChatThread = components['schemas']['ChatThread']
type ChatThreadDetailResponse = components['schemas']['ChatThreadDetailResponse']
type ChatThreadListResponse = components['schemas']['ChatThreadListResponse']
type ClarificationQuestion = components['schemas']['ClarificationQuestionV1']
type DeepSearchClarifyRequest = components['schemas']['DeepSearchClarifyRequestV1']
type DeepSearchBudget = components['schemas']['DeepSearchBudgetV1']
type DeepSearchBudgetReservation = components['schemas']['DeepSearchBudgetReservationV1']
type DeepSearchBudgetUsage = components['schemas']['DeepSearchBudgetUsageV1']
type DeepSearchPlan = components['schemas']['DeepSearchPlanViewV1']
type DeepSearchPlanDetailResponse = components['schemas']['DeepSearchPlanDetailResponse']
type DeepSearchPlanNode = components['schemas']['DeepSearchPlanNodeViewV1']
type DeepSearchPlanTransitionResponse = components['schemas']['DeepSearchPlanTransitionResponse']
type DeepSearchStateResponse = components['schemas']['DeepSearchStateResponse']
type RequirementPayload = components['schemas']['RequirementPayloadV1']
type RequirementVersion = components['schemas']['RequirementVersionV1']
type Skill = components['schemas']['SkillCatalogItem']
type SkillPlanUpdateRequest = components['schemas']['SkillPlanUpdateRequest']
type SkillPlanStatus = components['schemas']['SkillPlanStatus']
type SkillPlanVersionRequest = components['schemas']['SkillPlanVersionRequest']

type DeepSearchReportWire = DeepSearchReport & {
  requirement_content_hash: string
  problem_graph_hash: string
  plan_content_hash: string
  evidence_manifest_hash: string
  synthesis_content_hash: string
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value)
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('Canonical JSON forbids non-finite numbers')
    return JSON.stringify(value)
  }
  if (typeof value === 'string') return JSON.stringify(value.normalize('NFC'))
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (typeof value !== 'object') throw new TypeError(`Unsupported canonical JSON value: ${typeof value}`)
  const entries = Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => [key.normalize('NFC'), item] as const)
    .sort(([left], [right]) => Buffer.from(left).compare(Buffer.from(right)))
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`
}

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function canonicalHash(value: unknown): string {
  return sha256(canonicalJson(value))
}

const WORKSPACE_ID = 'ws_home_appliance_design'
const PROJECT_ID = 'prj_618_home_appliance'
const USER_ID = 'usr_current_designer'
const INPUT_TEXT = '研究企业 AI 助手的证据追溯与恢复能力'
const THREAD_TITLE = 'DeepSearch E2E 验收'
const PLAN_APPROVED_VERSION = 4
const REQUIREMENT_ID = 'requirement_deepsearch_e2e_v3'
const EVIDENCE_NODE_ID = 'node_skill_evidence'
const ANALYSIS_NODE_ID = 'node_skill_traceability_analysis'
const RISK_NODE_ID = 'node_skill_risk_context'
const EXPERT_NODE_ID = 'node_skill_expert_context'

const skills = [
  {
    id: 'skill_evidence', command: '$evidence-search', title: '公开资料检索', description: '收集并归一化外部证据',
    usage: '$evidence-search <goal>', placeholder: '输入研究目标', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', execution_readiness: 'complete', primary_stage: 'pre_design',
    capability_type: 'research', input_kinds: ['research_requirement'], output_kinds: ['evidence_manifest'], side_effect: 'read',
  },
  {
    id: 'skill_traceability_analysis', command: '$traceability-analysis', title: '证据追溯分析', description: '基于公开证据评估追溯与恢复机制',
    usage: '$traceability-analysis <evidence>', placeholder: '输入 Evidence Manifest', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', execution_readiness: 'complete', primary_stage: 'pre_design',
    capability_type: 'analysis', input_kinds: ['evidence_manifest'], output_kinds: ['traceability_analysis'], side_effect: 'read',
  },
  {
    id: 'skill_risk_context', command: '$risk-context', title: '风险补充分析', description: '补充可选风险背景，失败不阻断可信部分报告',
    usage: '$risk-context <analysis>', placeholder: '输入分析结果', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', execution_readiness: 'complete', primary_stage: 'pre_design',
    capability_type: 'analysis', input_kinds: ['traceability_analysis'], output_kinds: ['risk_context'], side_effect: 'read',
  },
  {
    id: 'skill_expert_context', command: '$expert-context', title: '补充专家视角', description: '补充非必需的专家判断',
    usage: '$expert-context <goal>', placeholder: '输入研究目标', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', execution_readiness: 'complete', primary_stage: 'pre_design',
    capability_type: 'analysis', input_kinds: ['evidence_manifest'], output_kinds: ['expert_context'], side_effect: 'read',
  },
] satisfies Skill[]

type Phase = 'clarification-1' | 'clarification-2' | 'plan' | 'running' | 'partial'

const FIRST_PROMPT = '主要研究区域是什么？'
const SECOND_PROMPT = '报告主要供谁决策？'

function clarificationQuestionId(version: number, ordinal: number, prompt: string): string {
  return `q_${version}_${ordinal}_${sha256(prompt.trim().normalize('NFC')).slice(0, 8)}`
}

const firstQuestion = {
  id: clarificationQuestionId(1, 1, FIRST_PROMPT),
  prompt: FIRST_PROMPT,
  required: true,
  answer_kind: 'text',
  options: [],
  max_length: 120,
  default_value: null,
} satisfies ClarificationQuestion

const secondQuestion = {
  id: clarificationQuestionId(2, 1, SECOND_PROMPT),
  prompt: SECOND_PROMPT,
  required: true,
  answer_kind: 'text',
  options: [],
  max_length: 120,
  default_value: null,
} satisfies ClarificationQuestion

interface RequirementIdentity {
  requestKey: string
  requestHash: string
}

function budgetUsage(overrides: Partial<DeepSearchBudgetUsage> = {}): DeepSearchBudgetUsage {
  return {
    active_seconds: 0,
    llm_calls: 0,
    tokens: 0,
    tool_calls: 0,
    evidence_items: 0,
    evidence_bytes: 0,
    artifact_bytes: 0,
    ...overrides,
  }
}

function settledReservation(
  name: string,
  actualUsage: DeepSearchBudgetUsage,
  resourceMaxima: DeepSearchBudgetUsage,
  scope: 'standard' | 'finalization' = 'standard',
): DeepSearchBudgetReservation {
  const logicalOperationKey = `${scope}:${name}:${canonicalHash({ run_id: RUN_ID, name })}`
  return {
    logical_operation_key: logicalOperationKey,
    invocation_key: canonicalHash({ logical_operation_key: logicalOperationKey, physical_attempt: 1 }),
    physical_attempt: 1,
    scope,
    resource_maxima: resourceMaxima,
    status: 'settled',
    actual_usage: actualUsage,
    tool_invocation: null,
  }
}

function deepSearchBudget(phase: Phase): DeepSearchBudget {
  const planningOperations = [
    'requirement_v1',
    ...(phase === 'clarification-1' ? [] : ['requirement_v2']),
    ...(['plan', 'running', 'partial'].includes(phase)
      ? ['requirement_v3', 'intent', 'problem_graph', 'plan']
      : []),
  ]
  const reservations = planningOperations.map((name, index) => settledReservation(
    name,
    budgetUsage({ active_seconds: 2, llm_calls: 1, tokens: 900 + index * 100 }),
    budgetUsage({ active_seconds: 120, llm_calls: 1, tokens: 32000 }),
  ))
  if (phase === 'running' || phase === 'partial') {
    for (const [index, nodeId] of [EVIDENCE_NODE_ID, ANALYSIS_NODE_ID].entries()) {
      reservations.push(settledReservation(
        `tool_${nodeId}`,
        budgetUsage({ active_seconds: 4, tool_calls: 1 }),
        budgetUsage({ active_seconds: 60, tool_calls: 1 }),
      ))
      reservations.push(settledReservation(
        `evidence_${nodeId}`,
        budgetUsage({ evidence_items: 1, evidence_bytes: 1024 + index * 256, artifact_bytes: 1536 + index * 256 }),
        budgetUsage({ evidence_items: 1, evidence_bytes: 1024 + index * 256, artifact_bytes: 1536 + index * 256 }),
      ))
    }
  }
  if (phase === 'partial') {
    for (const [index, name] of ['synthesis_v0', 'review_v0', 'synthesis_v1', 'review_v1'].entries()) {
      reservations.push(settledReservation(
        name,
        budgetUsage({ active_seconds: 3, llm_calls: 1, tokens: 1800 + index * 100 }),
        budgetUsage({ active_seconds: 120, llm_calls: 1, tokens: 32000 }),
      ))
    }
    reservations.push(
      settledReservation('manifest', budgetUsage({ active_seconds: 1, artifact_bytes: 4096 }), budgetUsage({ active_seconds: 30, artifact_bytes: 1048576 }), 'finalization'),
      settledReservation('coverage_v0', budgetUsage({ active_seconds: 1 }), budgetUsage({ active_seconds: 15 }), 'finalization'),
      settledReservation('coverage_v1', budgetUsage({ active_seconds: 1 }), budgetUsage({ active_seconds: 15 }), 'finalization'),
      settledReservation('report', budgetUsage({ active_seconds: 1, artifact_bytes: 8192 }), budgetUsage({ active_seconds: 30, artifact_bytes: 131072 }), 'finalization'),
    )
  }
  const consumed = reservations.reduce<DeepSearchBudgetUsage>((total, item) => {
    const actual = item.actual_usage ?? item.resource_maxima
    return budgetUsage({
      active_seconds: total.active_seconds + actual.active_seconds,
      llm_calls: total.llm_calls + actual.llm_calls,
      tokens: total.tokens + actual.tokens,
      tool_calls: total.tool_calls + actual.tool_calls,
      evidence_items: total.evidence_items + actual.evidence_items,
      evidence_bytes: total.evidence_bytes + actual.evidence_bytes,
      artifact_bytes: total.artifact_bytes + actual.artifact_bytes,
    })
  }, budgetUsage())
  return {
    schema_version: 'deepsearch-budget-v1',
    version: 1 + reservations.length * 2,
    limits: {
      active_seconds: 1800,
      llm_calls: 64,
      tokens: 250000,
      tool_calls: 24,
      evidence_items: 60,
      evidence_bytes: 524288,
      artifact_bytes: 10485760,
    },
    consumed,
    reservations,
    finalization_reserve: { active_seconds: 300, artifact_bytes: 1179648 },
    stage_recovery_attempts: {},
  }
}

function runCreateHash(clientTurnId: string): string {
  return canonicalHash({
    client_turn_id: clientTurnId,
    content: INPUT_TEXT,
    orchestration_mode: 'auto',
    planning_mode: 'deepsearch',
    retry_of_run_id: null,
    skill_name: null,
    thread_id: THREAD_ID,
    user_id: USER_ID,
  })
}

const REPORT_RENDERED_TEXT = [
  '# 企业 AI 助手可信研究报告',
  '',
  '## 执行摘要',
  '',
  '公开资料表明，证据追溯与失败恢复应共同纳入选型门槛。',
  '',
  '## 证据追溯能力',
  '',
  '候选产品必须保存来源、Evidence 与结论之间的稳定绑定。',
  '',
  '## 失败恢复能力',
  '',
  '高风险工作流应从持久化检查点恢复，且不得重复外部调用。',
  '',
  '## 局限性',
  '',
  '至少一个可选分析步骤未完成。',
].join('\n')

function run(phase: Phase, clientTurnId: string): AgentRun {
  const waiting = phase.startsWith('clarification') || phase === 'plan'
  const status: AgentRun['status'] = phase.startsWith('clarification')
    ? 'waiting_clarification'
    : phase === 'plan'
      ? 'waiting_plan_approval'
      : phase === 'running'
        ? 'running'
        : 'partial'
  return {
    id: RUN_ID,
    thread_id: THREAD_ID,
    user_id: USER_ID,
    workspace_id: WORKSPACE_ID,
    project_id: PROJECT_ID,
    input_text: INPUT_TEXT,
    client_turn_id: clientTurnId,
    status,
    skill_id: null,
    skill_name: null,
    plan_id: phase.startsWith('clarification') ? null : PLAN_ID,
    retry_of_run_id: null,
    planning_mode: 'deepsearch',
    create_request_hash: runCreateHash(clientTurnId),
    orchestration_version: 'v1',
    orchestration_mode: 'execute',
    writer_generation_epoch: null,
    requested_orchestration_mode: 'auto',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: phase === 'running' || phase === 'partial' ? 2 : 0,
    deadline_at: null,
    interaction_expires_at: waiting ? '2026-08-28T02:00:00Z' : null,
    absolute_expires_at: '2026-09-03T02:00:00Z',
    deepsearch_budget: deepSearchBudget(phase),
    paused_state: null,
    output_text: phase === 'partial' ? REPORT_RENDERED_TEXT : null,
    error_code: phase === 'partial' ? 'deepsearch_optional_node_failed' : null,
    created_at: NOW,
    updated_at: phase === 'partial' ? '2026-08-27T02:09:00Z' : NOW,
  }
}

function requirementVersionId(version: number): string {
  return `requirement_deepsearch_e2e_v${version}`
}

function requirementPayload(version: number): RequirementPayload {
  const clarificationHistory = [
    ...(version >= 2 ? [{
      round: 1,
      questions: [firstQuestion],
      answers: { [firstQuestion.id]: '中国大陆' },
    }] : []),
    ...(version >= 3 ? [{
      round: 2,
      questions: [secondQuestion],
      answers: { [secondQuestion.id]: '产品与研发负责人' },
    }] : []),
  ]
  return {
    goal: INPUT_TEXT,
    scope: {
      objects: ['企业 AI 助手'],
      regions: version >= 2 ? ['中国大陆'] : [],
      time_range: '最近 12 个月',
      audiences: version >= 3 ? ['产品与研发负责人'] : [],
      boundaries: ['仅使用可追溯公开资料'],
    },
    constraints: [{ kind: 'source', statement: '每个事实结论必须关联可验证来源' }],
    success_criteria: [
      { id: 'criterion_traceable', statement: '关键结论均可追溯到已封存 Evidence' },
      { id: 'criterion_recoverable', statement: '失败恢复机制具备可验证的持久化边界' },
    ],
    deliverables: ['结构化研究报告'],
    assumptions: [],
    ambiguities: version === 1
      ? [{ id: 'ambiguity_region', statement: '区域未知', blocking: true }]
      : version === 2
        ? [{ id: 'ambiguity_audience', statement: '决策受众未知', blocking: true }]
        : [],
    clarification_questions: version === 1 ? [firstQuestion] : version === 2 ? [secondQuestion] : [],
    clarification_history: clarificationHistory,
    clarification_round: version === 1 ? 1 : 2,
  }
}

function requirement(phase: Phase, identities: Map<number, RequirementIdentity>): RequirementVersion {
  const version = phase === 'clarification-1' ? 1 : phase === 'clarification-2' ? 2 : 3
  const identity = identities.get(version)
  if (!identity) throw new Error(`Missing Requirement request identity for v${version}`)
  const payload = requirementPayload(version)
  return {
    id: requirementVersionId(version),
    run_id: RUN_ID,
    version,
    schema_version: 'deepsearch-requirement-v1',
    request_key: identity.requestKey,
    request_hash: identity.requestHash,
    content_hash: canonicalHash({ schema_version: 'deepsearch-requirement-v1', payload }),
    derived_from_requirement_version_id: version === 1 ? null : requirementVersionId(version - 1),
    payload,
    created_at: `2026-08-27T02:00:0${version}Z`,
  }
}

const EVIDENCE_QUESTION_TEXT = '哪些公开资料可以验证候选产品的证据追溯能力？'
const RECOVERY_QUESTION_TEXT = '候选产品如何保证失败恢复且不重复外部调用？'
const EVIDENCE_QUESTION_ID = `question_${sha256(EVIDENCE_QUESTION_TEXT).slice(0, 16)}`
const RECOVERY_QUESTION_ID = `question_${sha256(RECOVERY_QUESTION_TEXT).slice(0, 16)}`
const PROBLEM_GRAPH_CONTENT = {
  schema_version: 'deepsearch-problem-graph-v1',
  requirement_version_id: REQUIREMENT_ID,
  questions: [
    {
      id: EVIDENCE_QUESTION_ID,
      question: EVIDENCE_QUESTION_TEXT,
      required: true,
      success_criterion_ids: ['criterion_traceable'],
      evidence_requirements: ['至少一个独立公开来源'],
      acceptance_criteria: ['来源可访问且结论有绑定'],
      depends_on: [],
    },
    {
      id: RECOVERY_QUESTION_ID,
      question: RECOVERY_QUESTION_TEXT,
      required: true,
      success_criterion_ids: ['criterion_recoverable'],
      evidence_requirements: ['至少一个描述恢复语义的公开来源'],
      acceptance_criteria: ['恢复边界与重复调用策略可验证'],
      depends_on: [EVIDENCE_QUESTION_ID],
    },
  ],
} satisfies Omit<components['schemas']['ProblemGraphV1'], 'content_hash'>
const PROBLEM_GRAPH_HASH = canonicalHash(PROBLEM_GRAPH_CONTENT)

function problemGraph(): components['schemas']['ProblemGraphV1'] {
  return { ...PROBLEM_GRAPH_CONTENT, content_hash: PROBLEM_GRAPH_HASH }
}

const PLAN_INTENT = {
  goal: INPUT_TEXT,
  primary_stage: 'pre_design',
  input_kinds: ['research_requirement'],
  deliverables: ['evidence_backed_report'],
  analysis_requirements: ['比较证据追溯与失败恢复'],
  presentation_requirements: ['Markdown 报告'],
  external_evidence_required: true,
  constraints: { external_write: false, project_scope: 'current', time_budget_seconds: 300 },
  explicit_skill_names: [],
  complexity: 'workflow',
} satisfies components['schemas']['SkillIntent']

interface NodeDefinition {
  id: string
  skillId: string
  title: string
  reason: string
  required: boolean
  dependsOn: string[]
  questionIds: string[]
  inputBindings: string[]
  outputContract: string[]
  requiredToolNames: string[]
}

const NODE_DEFINITIONS: NodeDefinition[] = [
  {
    id: EVIDENCE_NODE_ID,
    skillId: 'skill_evidence',
    title: '公开资料检索',
    reason: '检索并封存可信公开资料',
    required: true,
    dependsOn: [],
    questionIds: [EVIDENCE_QUESTION_ID],
    inputBindings: ['user.research_requirement'],
    outputContract: ['evidence_manifest'],
    requiredToolNames: ['web_research'],
  },
  {
    id: ANALYSIS_NODE_ID,
    skillId: 'skill_traceability_analysis',
    title: '证据追溯分析',
    reason: '基于第二个真实 Web 来源分析失败恢复边界',
    required: true,
    dependsOn: [EVIDENCE_NODE_ID],
    questionIds: [RECOVERY_QUESTION_ID],
    inputBindings: [`${EVIDENCE_NODE_ID}.evidence_manifest`],
    outputContract: ['traceability_analysis'],
    requiredToolNames: ['web_research'],
  },
  {
    id: RISK_NODE_ID,
    skillId: 'skill_risk_context',
    title: '风险补充分析',
    reason: '补充不阻断可信交付的可选风险背景',
    required: false,
    dependsOn: [ANALYSIS_NODE_ID],
    questionIds: [RECOVERY_QUESTION_ID],
    inputBindings: [`${ANALYSIS_NODE_ID}.traceability_analysis`],
    outputContract: ['risk_context'],
    requiredToolNames: [],
  },
  {
    id: EXPERT_NODE_ID,
    skillId: 'skill_expert_context',
    title: '补充专家视角',
    reason: '补充非必需的专家判断',
    required: false,
    dependsOn: [EVIDENCE_NODE_ID],
    questionIds: [RECOVERY_QUESTION_ID],
    inputBindings: [`${EVIDENCE_NODE_ID}.evidence_manifest`],
    outputContract: ['expert_context'],
    requiredToolNames: [],
  },
]

function selectedNodeDefinitions(includeExpert: boolean): NodeDefinition[] {
  return includeExpert ? NODE_DEFINITIONS : NODE_DEFINITIONS.filter((item) => item.id !== EXPERT_NODE_ID)
}

function resourceManifest() {
  const content = {
    schema_version: 'skill-resource-manifest-v1' as const,
    required_resources: [],
    resource_hashes: {},
  }
  return { ...content, content_hash: canonicalHash(content) }
}

function frozenNode(definition: NodeDefinition) {
  return {
    id: definition.id,
    skill_id: definition.skillId,
    skill_version: '1',
    skill_content_hash: canonicalHash({ skill_id: definition.skillId, version: '1' }),
    reason: definition.reason,
    task_id: 'deepsearch-research',
    scenario_id: 'evidence-backed-report',
    skill_registry_id: `registry_${definition.skillId}`,
    skill_status: 'validated',
    required: definition.required,
    depends_on: definition.dependsOn,
    parallel_group: null,
    condition: null,
    question_ids: definition.questionIds,
    input_bindings: definition.inputBindings,
    output_contract: definition.outputContract,
    knowledge_bindings: { required: [], optional: [], excluded: [] },
    required_tool_names: definition.requiredToolNames,
    resource_manifest: resourceManifest(),
    completion_criteria: ['产出可验证结果'],
    side_effect: 'read',
  }
}

function planContentHash(includeExpert: boolean): string {
  const definitions = selectedNodeDefinitions(includeExpert)
  return canonicalHash({
    schema_version: 'deepsearch-plan-v1',
    requirement_version_id: REQUIREMENT_ID,
    requirement_content_hash: canonicalHash({
      schema_version: 'deepsearch-requirement-v1',
      payload: requirementPayload(3),
    }),
    problem_graph_hash: PROBLEM_GRAPH_HASH,
    intent: PLAN_INTENT,
    routing_result: null,
    candidate_skill_ids: skills.map((skill) => skill.id),
    output_contract: ['evidence_backed_report'],
    synthesis_output_contract: ['deepsearch-report-v1'],
    capability_gaps: [],
    preferred_order: definitions.map((item) => item.skillId),
    nodes: definitions.map(frozenNode),
  })
}

const REQUIREMENT_CONTENT_HASH = canonicalHash({
  schema_version: 'deepsearch-requirement-v1',
  payload: requirementPayload(3),
})
const EDITED_PLAN_CONTENT_HASH = planContentHash(false)
const APPROVED_PLAN_ARTIFACT_ID = `artifact_${canonicalHash({
  kind: 'deepsearch_plan_snapshot',
  run_id: RUN_ID,
  plan_id: PLAN_ID,
  plan_version: PLAN_APPROVED_VERSION,
})}`
const EVIDENCE_ARTIFACT_HASH_DOCS = canonicalHash({ source: 'product-docs', version: 1 })
const EVIDENCE_ARTIFACT_HASH_RECOVERY = canonicalHash({ source: 'recovery-docs', version: 1 })
const EVIDENCE_MANIFEST = {
  schema_version: 'deepsearch-evidence-manifest-v1',
  run_id: RUN_ID,
  requirement_version_id: REQUIREMENT_ID,
  plan_id: PLAN_ID,
  plan_version: PLAN_APPROVED_VERSION,
  plan_content_hash: EDITED_PLAN_CONTENT_HASH,
  items: [
    {
      evidence_item_id: 'evidence_item_analysis',
      node_result_id: 'result_skill_traceability_analysis',
      evidence_artifact_id: 'artifact_evidence_recovery_docs',
      evidence_artifact_content_hash: EVIDENCE_ARTIFACT_HASH_RECOVERY,
      source_id: 'source_recovery_docs',
      origin_type: 'tool',
      question_ids: [RECOVERY_QUESTION_ID],
      success_criterion_ids: ['criterion_recoverable'],
    },
    {
      evidence_item_id: 'evidence_item_research',
      node_result_id: 'result_skill_evidence',
      evidence_artifact_id: 'artifact_evidence_product_docs',
      evidence_artifact_content_hash: EVIDENCE_ARTIFACT_HASH_DOCS,
      source_id: 'source_product_docs',
      origin_type: 'tool',
      question_ids: [EVIDENCE_QUESTION_ID],
      success_criterion_ids: ['criterion_traceable'],
    },
  ],
}
const EVIDENCE_MANIFEST_HASH = canonicalHash(EVIDENCE_MANIFEST)
const EVIDENCE_MANIFEST_ARTIFACT_ID = `artifact_deepsearch_manifest_${canonicalHash({
  run_id: RUN_ID,
  plan_id: PLAN_ID,
  plan_version: PLAN_APPROVED_VERSION,
})}`

function claimId(ordinal: number, claim: Omit<DeepSearchReport['claims'][number], 'id'>): string {
  return `claim_${canonicalHash({
    run_id: RUN_ID,
    plan_id: PLAN_ID,
    plan_version: PLAN_APPROVED_VERSION,
    revision_count: 1,
    ordinal,
    claim,
  })}`
}

const CLAIM_EVIDENCE_PAYLOAD = {
  text: '候选产品必须保存来源、Evidence 与结论之间的稳定绑定。',
  node_result_ids: ['result_skill_evidence'],
  evidence_item_ids: ['evidence_item_research'],
  source_ids: ['source_product_docs'],
  question_ids: [EVIDENCE_QUESTION_ID],
  success_criterion_ids: ['criterion_traceable'],
  recommendation: false,
} satisfies Omit<DeepSearchReport['claims'][number], 'id'>
const CLAIM_RECOVERY_PAYLOAD = {
  text: '高风险工作流应从持久化检查点恢复，且不得重复外部调用。',
  node_result_ids: ['result_skill_traceability_analysis'],
  evidence_item_ids: ['evidence_item_analysis'],
  source_ids: ['source_recovery_docs'],
  question_ids: [RECOVERY_QUESTION_ID],
  success_criterion_ids: ['criterion_recoverable'],
  recommendation: true,
} satisfies Omit<DeepSearchReport['claims'][number], 'id'>
const CLAIM_EVIDENCE = { id: claimId(1, CLAIM_EVIDENCE_PAYLOAD), ...CLAIM_EVIDENCE_PAYLOAD }
const CLAIM_RECOVERY = { id: claimId(2, CLAIM_RECOVERY_PAYLOAD), ...CLAIM_RECOVERY_PAYLOAD }
const SYNTHESIS_V1 = {
  schema_version: 'deepsearch-synthesis-v1',
  revision_count: 1,
  synthesis_mode: 'model',
  claims: [CLAIM_EVIDENCE, CLAIM_RECOVERY],
}
const SYNTHESIS_V1_HASH = canonicalHash(SYNTHESIS_V1)

function report(): DeepSearchReportWire {
  return {
    schema_version: 'deepsearch-report-v1',
    run_id: RUN_ID,
    requirement_version_id: REQUIREMENT_ID,
    plan_id: PLAN_ID,
    plan_version: PLAN_APPROVED_VERSION,
    requirement_content_hash: REQUIREMENT_CONTENT_HASH,
    problem_graph_hash: PROBLEM_GRAPH_HASH,
    plan_content_hash: EDITED_PLAN_CONTENT_HASH,
    evidence_manifest_hash: EVIDENCE_MANIFEST_HASH,
    synthesis_content_hash: SYNTHESIS_V1_HASH,
    review_outcome: 'pass',
    review_reason_code: null,
    report_status: 'partial',
    title: '企业 AI 助手可信研究报告',
    claims: [CLAIM_EVIDENCE, CLAIM_RECOVERY],
    executive_summary_claim_ids: [CLAIM_EVIDENCE.id, CLAIM_RECOVERY.id],
    sections: [
      { section_id: EVIDENCE_QUESTION_ID, server_heading: EVIDENCE_QUESTION_TEXT, claim_ids: [CLAIM_EVIDENCE.id] },
      { section_id: RECOVERY_QUESTION_ID, server_heading: RECOVERY_QUESTION_TEXT, claim_ids: [CLAIM_RECOVERY.id] },
    ],
    sources: [
      {
        source_id: 'source_product_docs',
        title: '产品公开文档',
        normalized_reference: 'https://example.com/product-docs',
        content_hash: EVIDENCE_ARTIFACT_HASH_DOCS,
      },
      {
        source_id: 'source_recovery_docs',
        title: '恢复机制公开文档',
        normalized_reference: 'https://example.com/recovery-docs',
        content_hash: EVIDENCE_ARTIFACT_HASH_RECOVERY,
      },
    ],
    limitations: [{
      code: 'deepsearch_optional_node_failed',
      related_ids: [RISK_NODE_ID],
      description: '至少一个可选分析步骤未完成。',
    }],
    rendered_text: REPORT_RENDERED_TEXT,
  }
}

const REPORT_CONTENT_HASH = canonicalHash(report())
const REPORT_ARTIFACT_ID = `artifact_deepsearch_report_${canonicalHash({
  run_id: RUN_ID,
  plan_id: PLAN_ID,
  plan_version: PLAN_APPROVED_VERSION,
  stage: 'terminal_committed',
  revision_count: 1,
  kind: 'deepsearch_report',
})}`

function node(definition: NodeDefinition, phase: Phase): DeepSearchPlanNode {
  const terminal = phase === 'partial'
  let status: DeepSearchPlanNode['status'] = 'pending'
  if (phase === 'running') {
    if (definition.id === EVIDENCE_NODE_ID) status = 'completed'
    else if (definition.id === ANALYSIS_NODE_ID) status = 'running'
  } else if (terminal) {
    status = definition.id === RISK_NODE_ID ? 'failed' : 'completed'
  }
  const attempted = status !== 'pending'
  const completed = status === 'completed' || status === 'failed'
  return {
    id: definition.id,
    skill_id: definition.skillId,
    skill_version: '1',
    reason: definition.reason,
    task_id: 'deepsearch-research',
    scenario_id: 'evidence-backed-report',
    required: definition.required,
    depends_on: definition.dependsOn,
    parallel_group: null,
    question_ids: definition.questionIds,
    output_contract: definition.outputContract,
    required_tool_names: definition.requiredToolNames,
    completion_criteria: ['产出可验证结果'],
    side_effect: 'read',
    status,
    attempt: attempted ? 1 : 0,
    error_code: status === 'failed' ? 'optional_context_unavailable' : null,
    started_at: attempted ? '2026-08-27T02:03:00Z' : null,
    completed_at: completed ? '2026-08-27T02:05:00Z' : null,
  }
}

function plan(
  phase: Phase,
  version: number,
  includeExpert: boolean,
  statusOverride?: SkillPlanStatus,
): DeepSearchPlan {
  const terminal = phase === 'partial'
  const definitions = selectedNodeDefinitions(includeExpert)
  const planStatus: SkillPlanStatus = statusOverride ?? (
    phase === 'plan' ? 'waiting_approval' : phase === 'running' ? 'running' : 'partial'
  )
  return {
    id: PLAN_ID,
    run_id: RUN_ID,
    version,
    status: planStatus,
    intent: PLAN_INTENT,
    routing_result: null,
    candidate_skill_ids: skills.map((skill) => skill.id),
    output_contract: ['evidence_backed_report'],
    synthesis_output_contract: ['deepsearch-report-v1'],
    capability_gaps: [],
    preferred_order: definitions.map((item) => item.skillId),
    nodes: definitions.map((item) => node(item, phase)),
    requirement_version_id: REQUIREMENT_ID,
    requirement_content_hash: REQUIREMENT_CONTENT_HASH,
    problem_graph_hash: PROBLEM_GRAPH_HASH,
    plan_content_hash: planContentHash(includeExpert),
    approved_plan_artifact_id: version >= PLAN_APPROVED_VERSION ? APPROVED_PLAN_ARTIFACT_ID : null,
    evidence_manifest_artifact_id: terminal ? EVIDENCE_MANIFEST_ARTIFACT_ID : null,
    evidence_manifest_hash: terminal ? EVIDENCE_MANIFEST_HASH : null,
    report_artifact_id: terminal ? REPORT_ARTIFACT_ID : null,
    report_content_hash: terminal ? REPORT_CONTENT_HASH : null,
    report_revision_count: terminal ? 1 : 0,
    finalization_stage: terminal ? 'terminal_committed' : 'none',
    finalization_version: terminal ? 9 : 0,
    degradation: null,
    created_at: NOW,
    updated_at: `2026-08-27T02:0${Math.min(version, 9)}:00Z`,
  }
}

function aggregate(
  phase: Phase,
  planVersion: number,
  includeExpert: boolean,
  clientTurnId: string,
  identities: Map<number, RequirementIdentity>,
): DeepSearchStateResponse {
  const terminal = phase === 'partial'
  return {
    run: run(phase, clientTurnId),
    active_requirement: requirement(phase, identities),
    problem_graph: phase.startsWith('clarification') ? null : problemGraph(),
    plan: phase.startsWith('clarification') ? null : plan(phase, planVersion, includeExpert),
    evidence_coverage: terminal ? {
      schema_version: 'deepsearch-evidence-coverage-v1',
      revision_count: 1,
      synthesis_content_hash: SYNTHESIS_V1_HASH,
      required_question_ids: [EVIDENCE_QUESTION_ID, RECOVERY_QUESTION_ID],
      covered_question_ids: [EVIDENCE_QUESTION_ID, RECOVERY_QUESTION_ID],
      uncovered_question_ids: [],
      required_success_criterion_ids: ['criterion_traceable', 'criterion_recoverable'],
      covered_success_criterion_ids: ['criterion_traceable', 'criterion_recoverable'],
      uncovered_success_criterion_ids: [],
      validated_claim_ids: [CLAIM_EVIDENCE.id, CLAIM_RECOVERY.id],
      invalid_claim_ids: [],
      validated_source_ids: ['source_product_docs', 'source_recovery_docs'],
      invalid_source_ids: [],
      validated_node_result_ids: ['result_skill_evidence', 'result_skill_traceability_analysis'],
      invalid_node_result_ids: [],
      external_evidence_is_real: true,
      passed: true,
      gap_codes: [],
    } : null,
    report_review: terminal ? {
      revision_count: 1,
      outcome: 'pass',
      reason_code: null,
      unsupported_claim_ids: [],
      contradictory_claim_ids: [],
      missing_section_ids: [],
      limitation_codes: [],
    } : null,
    retry_disposition: 'none',
  }
}

async function enableDeepSearch(page: Page) {
  await page.route('**/api/bootstrap', async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    await route.fulfill({
      response,
      json: {
        ...payload,
        agent_runtime_enabled: true,
        skill_orchestration_mode: 'execute',
        deepsearch_availability: {
          available: true,
          enabled: true,
          runtime_mode: 'execute',
          core_ready: true,
          reason_code: null,
        },
      },
    })
  })
}

async function installDeepSearchApi(page: Page) {
  let phase: Phase = 'clarification-1'
  let planVersion = 1
  let includeExpert = true
  let patchAttempts = 0
  let stateReads = 0
  let runCreated = false
  let createClientTurnId: string | null = null
  const requirementIdentities = new Map<number, RequirementIdentity>()
  const createRequests: AgentRunCreateRequest[] = []
  const clarificationRequests: DeepSearchClarifyRequest[] = []
  const planPatchRequests: SkillPlanUpdateRequest[] = []
  const planApprovalRequests: SkillPlanVersionRequest[] = []
  let releaseExecutionGate = () => {}
  const executionGate = new Promise<void>((resolve) => { releaseExecutionGate = resolve })

  const chatThread = {
    id: THREAD_ID,
    workspace_id: WORKSPACE_ID,
    project_id: PROJECT_ID,
    user_id: USER_ID,
    title: THREAD_TITLE,
    pinned: false,
    status: 'active',
    created_at: NOW,
    updated_at: NOW,
  } satisfies ChatThread

  const currentRun = (): AgentRun => {
    if (!createClientTurnId) throw new Error('DeepSearch Run has not been created')
    return run(phase, createClientTurnId)
  }
  const currentAggregate = (): DeepSearchStateResponse => {
    if (!createClientTurnId) throw new Error('DeepSearch Run has not been created')
    return aggregate(phase, planVersion, includeExpert, createClientTurnId, requirementIdentities)
  }
  const threadDetail = (): ChatThreadDetailResponse => ({
    thread: chatThread,
    messages: runCreated ? [{
      id: 'message_deepsearch_user',
      thread_id: THREAD_ID,
      role: 'user',
      content: INPUT_TEXT,
      scope: 'private',
      sources: [],
      created_at: NOW,
    }] : [],
    turn_traces: [],
    latest_research_run_id: runCreated ? RUN_ID : null,
  })

  const clarificationIdentity = (request: DeepSearchClarifyRequest): RequirementIdentity => {
    const normalizedAnswers = Object.fromEntries(
      Object.entries(request.answers).map(([questionId, answer]) => {
        if (typeof answer === 'string') {
          return [questionId.normalize('NFC'), answer.trim().normalize('NFC')]
        }
        if (Array.isArray(answer) && answer.every((item): item is string => typeof item === 'string')) {
          return [questionId.normalize('NFC'), answer.map((item) => item.trim().normalize('NFC')).sort()]
        }
        throw new TypeError('E2E clarification answers must be strings or string arrays')
      }),
    )
    return {
      requestKey: request.client_turn_id,
      requestHash: canonicalHash({
        run_id: RUN_ID,
        expected_requirement_version: request.expected_requirement_version,
        normalized_answers: normalizedAnswers,
      }),
    }
  }

  await page.route('**/api/chat/skills', (route) => route.fulfill({ json: { items: skills } }))
  await page.route('**/api/chat/threads', (route) => {
    const response = { items: [chatThread] } satisfies ChatThreadListResponse
    return route.fulfill({ json: response })
  })
  await page.route(`**/api/chat/threads/${THREAD_ID}`, (route) => route.fulfill({ json: threadDetail() }))
  await page.route('**/api/agent/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const request = route.request().postDataJSON() as AgentRunCreateRequest
    createRequests.push(request)
    createClientTurnId = request.client_turn_id
    requirementIdentities.set(1, {
      requestKey: request.client_turn_id,
      requestHash: runCreateHash(request.client_turn_id),
    })
    runCreated = true
    phase = 'clarification-1'
    const response = { item: currentRun() }
    await route.fulfill({ status: 202, json: response })
  })
  await page.route(`**/api/artifacts/${REPORT_ARTIFACT_ID}`, (route) => route.fulfill({
    contentType: 'application/json',
    body: canonicalJson(report()),
  }))
  await page.route(`**/api/agent/runs/${RUN_ID}/**`, async (route: Route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()

    if (url.pathname.endsWith('/events/stream')) {
      if (phase !== 'running' && phase !== 'partial') {
        await route.fulfill({ status: 204, body: '' })
        return
      }
      if (phase === 'running') await executionGate
      const finalizationStages = [
        'nodes_terminal',
        'evidence_manifest_sealed',
        'synthesis_v0_saved',
        'coverage_v0_checked',
        'review_v0_checked',
        'synthesis_v1_saved',
        'coverage_v1_checked',
        'review_v1_checked',
        'terminal_committed',
      ] as const
      const events: AgentRunEvent[] = finalizationStages.map((toStage, index) => ({
        id: `event_deepsearch_finalization_${index + 1}`,
        run_id: RUN_ID,
        sequence: index + 1,
        event_type: 'deepsearch_finalization_stage_changed',
        payload: {
          plan_id: PLAN_ID,
          from_stage: index === 0 ? 'none' : finalizationStages[index - 1],
          to_stage: toStage,
          finalization_version: index + 1,
          input_hash: canonicalHash({ plan_id: PLAN_ID, to_stage: toStage, version: index + 1 }),
        },
        created_at: `2026-08-27T02:0${Math.min(index + 1, 9)}:00Z`,
      }))
      events.push({
        id: 'event_deepsearch_partial',
        run_id: RUN_ID,
        sequence: events.length + 1,
        event_type: 'run_partial',
        payload: {
          plan_id: PLAN_ID,
          report_artifact_id: REPORT_ARTIFACT_ID,
          error_code: 'deepsearch_optional_node_failed',
        },
        created_at: '2026-08-27T02:09:00Z',
      })
      const body = events.map((event) => (
        `id: ${event.sequence}\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`
      )).join('')
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body,
      })
      return
    }

    if (url.pathname.endsWith('/deepsearch/clarify') && method === 'POST') {
      const request = route.request().postDataJSON() as DeepSearchClarifyRequest
      clarificationRequests.push(request)
      requirementIdentities.set(request.expected_requirement_version + 1, clarificationIdentity(request))
      phase = phase === 'clarification-1' ? 'clarification-2' : 'plan'
      await route.fulfill({ status: 202, json: currentAggregate() })
      return
    }

    if (url.pathname.endsWith('/deepsearch') && method === 'GET') {
      stateReads += 1
      await route.fulfill({ json: currentAggregate() })
      return
    }

    if (url.pathname.endsWith('/plan/approve') && method === 'POST') {
      const request = route.request().postDataJSON() as SkillPlanVersionRequest
      planApprovalRequests.push(request)
      planVersion = request.expected_version + 1
      phase = 'running'
      const response = {
        plan: plan(phase, planVersion, includeExpert, 'approved'),
        run: currentRun(),
      } satisfies DeepSearchPlanTransitionResponse
      await route.fulfill({ json: response })
      return
    }

    if (url.pathname.endsWith('/plan') && method === 'PATCH') {
      const request = route.request().postDataJSON() as SkillPlanUpdateRequest
      planPatchRequests.push(request)
      patchAttempts += 1
      if (patchAttempts === 1) {
        planVersion = 2
        await route.fulfill({ status: 409, json: { detail: 'DeepSearch Plan version conflict' } })
        return
      }
      planVersion = 3
      includeExpert = false
      const response = {
        plan: plan(phase, planVersion, includeExpert),
        results: [],
        synthesis: null,
      } satisfies DeepSearchPlanDetailResponse
      await route.fulfill({ json: response })
      return
    }

    if (url.pathname.endsWith('/plan') && method === 'GET') {
      const response = {
        plan: plan(phase, planVersion, includeExpert),
        results: [],
        synthesis: null,
      } satisfies DeepSearchPlanDetailResponse
      await route.fulfill({ json: response })
      return
    }

    await route.continue()
  })
  await page.route(`**/api/agent/runs/${RUN_ID}`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { item: currentRun() } })
      return
    }
    await route.continue()
  })

  return {
    createRequests: () => [...createRequests],
    clarificationRequests: () => [...clarificationRequests],
    planPatchRequests: () => [...planPatchRequests],
    planApprovalRequests: () => [...planApprovalRequests],
    stateReads: () => stateReads,
    releaseExecution: () => {
      phase = 'partial'
      releaseExecutionGate()
    },
  }
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

test('runs the explicit DeepSearch flow through two clarifications, plan resync, sealed report, and reload', async ({ page }) => {
  await enableDeepSearch(page)
  const api = await installDeepSearchApi(page)
  await loginAs(page)
  await page.goto('/workspace')
  await page.getByRole('button', { name: THREAD_TITLE, exact: true }).click()
  await expect(page).toHaveURL(`/workspace/thread/${THREAD_ID}`)

  await page.getByRole('button', { name: 'DeepSearch', exact: true }).click()
  await expect(page.getByRole('button', { name: 'DeepSearch', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByLabel('消息').fill(INPUT_TEXT)
  const create = page.waitForRequest((request) => request.url().endsWith('/api/agent/runs') && request.method() === 'POST')
  await page.getByRole('button', { name: '发送' }).click()
  const createRequest = (await create).postDataJSON() as AgentRunCreateRequest
  expect(createRequest).toEqual({
    thread_id: THREAD_ID,
    content: INPUT_TEXT,
    client_turn_id: expect.any(String),
    orchestration_mode: 'auto',
    planning_mode: 'deepsearch',
  })
  expect(createRequest.client_turn_id).not.toHaveLength(0)
  expect(api.createRequests()).toEqual([createRequest])
  await expect(page).toHaveURL(new RegExp(`${THREAD_ID}\\?run=${RUN_ID}$`))

  await expect(page.getByText('第 1 / 3 轮')).toBeVisible()
  await page.getByRole('textbox', { name: /主要研究区域是什么/ }).fill('中国大陆')
  const firstClarification = page.waitForRequest((request) => (
    request.url().endsWith(`/api/agent/runs/${RUN_ID}/deepsearch/clarify`) && request.method() === 'POST'
  ))
  await page.getByRole('button', { name: '提交本轮回答' }).click()
  const firstClarificationRequest = (await firstClarification).postDataJSON() as DeepSearchClarifyRequest
  await expect(page.getByText('第 2 / 3 轮')).toBeVisible()
  await expect(page.getByText('已完成 1 轮澄清')).toBeVisible()
  await page.getByRole('textbox', { name: /报告主要供谁决策/ }).fill('产品与研发负责人')
  const secondClarification = page.waitForRequest((request) => (
    request.url().endsWith(`/api/agent/runs/${RUN_ID}/deepsearch/clarify`) && request.method() === 'POST'
  ))
  await page.getByRole('button', { name: '提交本轮回答' }).click()
  const secondClarificationRequest = (await secondClarification).postDataJSON() as DeepSearchClarifyRequest

  await expect(page.getByRole('heading', { name: '执行前确认计划' })).toBeVisible()
  await expect(page.getByText('已完成 2 轮澄清')).toBeVisible()
  expect(firstClarificationRequest).toEqual({
    client_turn_id: expect.any(String),
    expected_requirement_version: 1,
    answers: { [firstQuestion.id]: '中国大陆' },
  })
  expect(secondClarificationRequest).toEqual({
    client_turn_id: expect.any(String),
    expected_requirement_version: 2,
    answers: { [secondQuestion.id]: '产品与研发负责人' },
  })
  expect(firstClarificationRequest.client_turn_id).not.toHaveLength(0)
  expect(secondClarificationRequest.client_turn_id).not.toHaveLength(0)
  expect(firstClarificationRequest.client_turn_id).not.toBe(secondClarificationRequest.client_turn_id)
  expect(api.clarificationRequests()).toEqual([firstClarificationRequest, secondClarificationRequest])

  await page.getByRole('button', { name: '移除 补充专家视角' }).click()
  const conflictingPatch = page.waitForRequest((request) => (
    request.url().endsWith(`/api/agent/runs/${RUN_ID}/plan`) && request.method() === 'PATCH'
  ))
  await page.getByRole('button', { name: '保存调整' }).click()
  await conflictingPatch
  await expect(page.getByRole('alert')).toContainText('DeepSearch Plan version conflict')
  await expect(page.getByText('Skill plan · v2')).toBeVisible()

  await page.getByRole('button', { name: '移除 补充专家视角' }).click()
  const acceptedPatch = page.waitForRequest((request) => (
    request.url().endsWith(`/api/agent/runs/${RUN_ID}/plan`) && request.method() === 'PATCH'
  ))
  await page.getByRole('button', { name: '保存调整' }).click()
  await acceptedPatch
  await expect(page.getByText('Skill plan · v3')).toBeVisible()
  await expect(page.getByRole('button', { name: '移除 补充专家视角' })).toHaveCount(0)
  const selectedSkillIds = ['skill_evidence', 'skill_traceability_analysis', 'skill_risk_context']
  expect(api.planPatchRequests()).toEqual([
    { expected_version: 1, selected_skill_ids: selectedSkillIds, preferred_order: selectedSkillIds },
    { expected_version: 2, selected_skill_ids: selectedSkillIds, preferred_order: selectedSkillIds },
  ])

  const approval = page.waitForRequest((request) => (
    request.url().endsWith(`/api/agent/runs/${RUN_ID}/plan/approve`) && request.method() === 'POST'
  ))
  await page.getByRole('button', { name: '确认并开始执行' }).click()
  await approval
  expect(api.planApprovalRequests()).toEqual([{ expected_version: 3 }])
  await expect(page.getByText('当前阶段：执行')).toBeVisible()
  await expect(page.getByRole('heading', { name: '执行计划进行中' })).toBeVisible()
  await expect(page.locator('[data-node-status="completed"]')).toHaveCount(1)
  await expect(page.locator('[data-node-status="running"]')).toHaveCount(1)

  api.releaseExecution()
  await expect(page.getByText('当前阶段：报告')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('报告已封存')).toBeVisible()
  await expect(page.getByText('Report Review · 审核通过')).toBeVisible()
  await expect(page.getByText('revision 1')).toBeVisible()
  await expect(page.getByText('Sealed report')).toBeVisible()
  await expect(page.getByRole('heading', { name: '企业 AI 助手可信研究报告' })).toBeVisible()
  await expect(page.getByText('部分报告')).toBeVisible()
  await expect(page.getByText('至少一个可选分析步骤未完成。')).toBeVisible()
  await expect(page.getByRole('link', { name: '独立查看' })).toHaveAttribute(
    'href',
    `/api/agent/runs/${RUN_ID}/report.html`,
  )
  await expect(page.getByRole('link', { name: '下载 HTML' })).toHaveAttribute(
    'href',
    `/api/agent/runs/${RUN_ID}/report.html?download=true`,
  )
  await expect(page.locator('[data-node-status="completed"]')).toHaveCount(2)
  await expect(page.locator('[data-node-status="failed"]')).toHaveCount(1)
  await expect(page.getByRole('link', { name: '产品公开文档' })).toHaveAttribute('target', '_blank')

  const readsBeforeReload = api.stateReads()
  await page.reload()
  await expect(page.getByTestId('deepsearch-workspace')).toBeVisible()
  await expect(page.getByText('当前阶段：报告')).toBeVisible()
  await expect(page.getByText('已完成 2 轮澄清')).toBeVisible()
  await expect(page.getByRole('heading', { name: '企业 AI 助手可信研究报告' })).toBeVisible()
  await expect.poll(api.stateReads).toBeGreaterThan(readsBeforeReload)

  await page.goto('/workspace')
  await page.getByRole('button', { name: THREAD_TITLE, exact: true }).click()
  await expect(page).toHaveURL(`/workspace/thread/${THREAD_ID}`)
  await expect(page.getByTestId('deepsearch-workspace')).toBeVisible()
  await expect(page.getByText('当前阶段：报告')).toBeVisible()
  await expect(page.getByRole('heading', { name: '企业 AI 助手可信研究报告' })).toBeVisible()
})
