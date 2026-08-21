import type { PlanStepRenderV1, StepStatus, WorkbenchStepRenderV1 } from './types'

export interface DagNode {
  id: string
  stepNumber: number
  name: string
  actorType: PlanStepRenderV1['actor_type']
  actorId: string
  dependsOn: number[]
  status: StepStatus
  failureCode: string | null
  layer: number
}

export interface DagEdge {
  id: string
  source: number
  target: number
  status: StepStatus
}

export interface ResearchDag {
  nodes: DagNode[]
  edges: DagEdge[]
  layers: number[][]
}

function statusFor(stepNumber: number, attempts: readonly WorkbenchStepRenderV1[]): Pick<DagNode, 'status' | 'failureCode'> {
  const attempt = attempts.find((item) => item.step_number === stepNumber)
  return {
    status: attempt?.status ?? 'pending',
    failureCode: attempt?.failure_code ?? null,
  }
}

/** Builds a deterministic, visual-only DAG model from the sealed plan and public step statuses. */
export function buildResearchDag(
  steps: readonly PlanStepRenderV1[],
  attempts: readonly WorkbenchStepRenderV1[] = [],
): ResearchDag {
  const known = new Set(steps.map((step) => step.step_number))
  const layerByStep = new Map<number, number>()

  for (const step of [...steps].sort((left, right) => left.step_number - right.step_number)) {
    const dependencies = step.depends_on.filter((dependency) => known.has(dependency))
    const layer = dependencies.length === 0
      ? 0
      : Math.max(...dependencies.map((dependency) => layerByStep.get(dependency) ?? 0)) + 1
    layerByStep.set(step.step_number, layer)
  }

  const nodes = steps.map((step) => ({
    id: `research-step-${step.step_number}`,
    stepNumber: step.step_number,
    name: step.name,
    actorType: step.actor_type,
    actorId: step.actor_id,
    dependsOn: step.depends_on,
    layer: layerByStep.get(step.step_number) ?? 0,
    ...statusFor(step.step_number, attempts),
  }))
  const layers: number[][] = []
  for (const node of nodes) {
    const layer = layers[node.layer] ?? []
    layer.push(node.stepNumber)
    layers[node.layer] = layer
  }
  const nodesByStep = new Map(nodes.map((node) => [node.stepNumber, node]))
  const edges = nodes.flatMap((node) => node.dependsOn
    .filter((dependency) => nodesByStep.has(dependency))
    .map((dependency) => ({
      id: `${dependency}-${node.stepNumber}`,
      source: dependency,
      target: node.stepNumber,
      status: node.status,
    })))

  return { nodes, edges, layers }
}

export function describeResearchDag(dag: ResearchDag): string {
  if (dag.nodes.length === 0) return '研究执行流程，没有步骤。'
  const descriptions = dag.nodes.map((node) => {
    const dependency = node.dependsOn.length > 0 ? `，依赖步骤 ${node.dependsOn.join('、')}` : '，没有前置步骤'
    return `步骤 ${node.stepNumber}，${node.name}，${node.actorType} ${node.actorId}${dependency}，状态 ${node.status}`
  })
  return `研究执行流程，共 ${dag.nodes.length} 个步骤。${descriptions.join('；')}。`
}
