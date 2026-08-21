import { adaptWorkbenchAggregate, canonicalSha256 } from './adapter'
import type { ResearchV3WorkbenchAggregateV1 } from './types'

export type ResearchV3CommandType =
  | 'clarify'
  | 'select_candidate'
  | 'revise_plan'
  | 'confirm_plan'
  | 'approval'
  | 'execute'
  | 'retry'
  | 'skip'
  | 'abort'
  | 'cancel'
  | 'purge'

interface MutationRequestBase {
  expected_state_version: number
  request_hash: string
}

export interface ResearchV3ClarifyRequest extends MutationRequestBase {
  answers: Array<{ question_key: string; answer: string }>
}

export interface ResearchV3CandidateSelectRequest extends MutationRequestBase {
  candidate_id: 'depth' | 'speed'
}

export interface ResearchV3ReviseRequest extends MutationRequestBase {
  plan_version_id: string
  candidate_id?: 'depth' | 'speed' | null
  revision_note?: string | null
  assumptions?: Array<{ key: string; value: string }>
  remove_optional_step_numbers?: number[]
}

export interface ResearchV3ConfirmRequest extends MutationRequestBase {
  plan_version_id: string
}

export interface ResearchV3ApprovalRequest extends MutationRequestBase {
  gate_key: string
  plan_version_id: string
  role: 'owner' | 'legal' | 'security'
  decision: 'approve' | 'reject'
}

export interface ResearchV3ExecuteRequest extends MutationRequestBase {
  plan_version_id: string
}

interface ResearchV3RecoveryRequest extends MutationRequestBase {
  attempt_id: string
  failed_step_number: number
}

export type ResearchV3RetryRequest = ResearchV3RecoveryRequest

export interface ResearchV3SkipRequest extends ResearchV3RecoveryRequest {
  reason: string
}

export interface ResearchV3AbortRequest extends ResearchV3RecoveryRequest {
  reason?: string | null
}

export interface ResearchV3CancelRequest extends MutationRequestBase {
  reason?: string | null
}

export interface ResearchV3PurgeRequest extends MutationRequestBase {
  confirmation: 'PURGE'
}

export interface ResearchV3RequestByCommand {
  clarify: ResearchV3ClarifyRequest
  select_candidate: ResearchV3CandidateSelectRequest
  revise_plan: ResearchV3ReviseRequest
  confirm_plan: ResearchV3ConfirmRequest
  approval: ResearchV3ApprovalRequest
  execute: ResearchV3ExecuteRequest
  retry: ResearchV3RetryRequest
  skip: ResearchV3SkipRequest
  abort: ResearchV3AbortRequest
  cancel: ResearchV3CancelRequest
  purge: ResearchV3PurgeRequest
}

export type ResearchV3RequestInput<C extends ResearchV3CommandType> = Omit<
  ResearchV3RequestByCommand[C],
  'request_hash'
>

export function buildResearchV3Request<C extends ResearchV3CommandType>(
  runId: string,
  command: C,
  request: ResearchV3RequestInput<C>,
): ResearchV3RequestByCommand[C] {
  const defaults: Partial<Record<ResearchV3CommandType, Record<string, unknown>>> = {
    revise_plan: {
      candidate_id: null,
      revision_note: null,
      assumptions: [],
      remove_optional_step_numbers: [],
    },
    abort: { reason: null },
    cancel: { reason: null },
  }
  const canonicalRequest = Object.fromEntries(
    Object.entries({ ...(defaults[command] ?? {}), ...request })
      .filter(([, value]) => value !== undefined),
  )
  const requestHash = canonicalSha256({
    command_type: command,
    run_id: runId,
    request: canonicalRequest,
  })
  return { ...canonicalRequest, request_hash: requestHash } as ResearchV3RequestByCommand[C]
}

export function researchV3IdempotencyKey<C extends ResearchV3CommandType>(
  command: C,
  request: ResearchV3RequestByCommand[C],
): string {
  return `web:${command}:${request.expected_state_version}:${request.request_hash.slice(0, 24)}`
}

export interface ResearchV3MutationResponse<C extends ResearchV3CommandType = ResearchV3CommandType> {
  run_id: string
  command_type: C
  request_hash: string
  previous_state_version: number
  state_version: number
  accepted: true
  replayed: boolean
}

export interface ResearchV3PurgeResponse extends ResearchV3MutationResponse<'purge'> {
  purged_artifact_count: number
}

export type ResearchV3ResponseByCommand<C extends ResearchV3CommandType> =
  C extends 'purge' ? ResearchV3PurgeResponse : ResearchV3MutationResponse<C>

export interface ResearchV3PlanStreamResult {
  schema_version: 'research-v3-plan-stream-result-v1'
  event_id: string
  run_id: string
  state_version: number
  aggregate: ResearchV3WorkbenchAggregateV1
}

export interface ResearchV3AggregateQuery {
  queryKey: readonly ['research-v3-aggregate', string]
  queryFn: () => Promise<ResearchV3WorkbenchAggregateV1>
}

export interface ResearchV3ApiClient {
  readAggregate(runId: string): Promise<ResearchV3WorkbenchAggregateV1>
  refreshAggregate(runId: string): Promise<ResearchV3WorkbenchAggregateV1>
  planStreamUrl(runId: string, afterStateVersion?: number): string
  mutate<C extends ResearchV3CommandType>(
    runId: string,
    command: C,
    idempotencyKey: string,
    request: ResearchV3RequestByCommand[C],
  ): Promise<ResearchV3ResponseByCommand<C>>
}

const COMMAND_PATH: Record<ResearchV3CommandType, string> = {
  clarify: 'research/clarify',
  select_candidate: 'research/candidates/select',
  revise_plan: 'research/plans/revise',
  confirm_plan: 'research/plans/confirm',
  approval: 'research/approvals',
  execute: 'research/execute',
  retry: 'research/recovery/retry',
  skip: 'research/recovery/skip',
  abort: 'research/recovery/abort',
  cancel: 'research/cancel',
  purge: 'research-data',
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function requireSuccessful(response: Response): Response {
  if (!response.ok) throw new Error(`research-v3 API request failed with ${response.status}`)
  return response
}

function parseRepositoryAggregate(value: unknown): ResearchV3WorkbenchAggregateV1 {
  // This call performs the feature's exact schema and cross-record semantic validation.
  const rendered = adaptWorkbenchAggregate(value)
  if (rendered.render_kind !== 'current' || rendered.provenance.source_kind !== 'repository_projection') {
    throw new TypeError('research-v3 API accepts only authoritative repository projections')
  }
  return value as ResearchV3WorkbenchAggregateV1
}

function parseMutationResponse<C extends ResearchV3CommandType>(
  value: unknown,
  command: C,
  runId: string,
  request: ResearchV3RequestByCommand[C],
): ResearchV3ResponseByCommand<C> {
  const item = record(value, 'research-v3 mutation response')
  const expectedKeys = new Set([
    'run_id',
    'command_type',
    'request_hash',
    'previous_state_version',
    'state_version',
    'accepted',
    'replayed',
    ...(command === 'purge' ? ['purged_artifact_count'] : []),
  ])
  if (Object.keys(item).some((key) => !expectedKeys.has(key)) || Object.keys(item).length !== expectedKeys.size) {
    throw new TypeError('research-v3 mutation response fields are not exact')
  }
  if (
    item.run_id !== runId
    || item.command_type !== command
    || item.request_hash !== request.request_hash
    || item.previous_state_version !== request.expected_state_version
    || !Number.isInteger(item.state_version)
    || item.state_version !== (item.previous_state_version as number) + 1
    || item.accepted !== true
    || typeof item.replayed !== 'boolean'
    || (command === 'purge' && (!Number.isInteger(item.purged_artifact_count) || (item.purged_artifact_count as number) < 0))
  ) {
    throw new TypeError('research-v3 mutation response is invalid')
  }
  return item as unknown as ResearchV3ResponseByCommand<C>
}

export function createResearchV3ApiClient(
  fetcher: typeof fetch = fetch,
  baseUrl = '/api/agent/runs',
): ResearchV3ApiClient {
  const runUrl = (runId: string) => `${baseUrl}/${encodeURIComponent(runId)}`
  const read = async (url: string) => {
    const response = requireSuccessful(await fetcher(url, { method: 'GET', headers: { Accept: 'application/json' } }))
    return parseRepositoryAggregate(await response.json())
  }

  return {
    readAggregate: (runId) => read(`${runUrl(runId)}/research`),
    refreshAggregate: (runId) => read(`${runUrl(runId)}/research/refresh`),
    planStreamUrl: (runId, afterStateVersion) => {
      const url = `${runUrl(runId)}/research/plan/stream`
      return afterStateVersion === undefined ? url : `${url}?after_state_version=${afterStateVersion}`
    },
    mutate: async (runId, command, idempotencyKey, request) => {
      const response = requireSuccessful(await fetcher(`${runUrl(runId)}/${COMMAND_PATH[command]}`, {
        method: command === 'purge' ? 'DELETE' : 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify(request),
      }))
      return parseMutationResponse(await response.json(), command, runId, request)
    },
  }
}

export function researchV3AggregateQuery(
  client: ResearchV3ApiClient,
  runId: string,
): ResearchV3AggregateQuery {
  return {
    queryKey: ['research-v3-aggregate', runId] as const,
    queryFn: () => client.readAggregate(runId),
  }
}
