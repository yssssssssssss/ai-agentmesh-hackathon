import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'

import { workspaceKeys } from '../workspace/keys'
import type { AgentRun, WorkspaceScope } from '../workspace/types'
import { adaptWorkbenchAggregate } from './adapter'
import {
  buildResearchV3Request,
  createResearchV3ApiClient,
  researchV3IdempotencyKey,
  type ResearchV3CommandType,
  type ResearchV3RequestInput,
} from './apiClient'
import { ResearchWorkbench } from './ResearchWorkbench'

const PREVIEW_COMMANDS = new Set<ResearchV3CommandType>([
  'clarify',
  'select_candidate',
  'revise_plan',
  'confirm_plan',
])

type PreviewCommand = 'clarify' | 'select_candidate' | 'revise_plan' | 'confirm_plan'

export interface ResearchWorkbenchContainerProps {
  scope: WorkspaceScope
  run: AgentRun
}

export function ResearchWorkbenchContainer({ scope, run }: ResearchWorkbenchContainerProps) {
  const client = useMemo(() => createResearchV3ApiClient(), [])
  const queryClient = useQueryClient()
  const [pendingCommand, setPendingCommand] = useState<PreviewCommand | null>(null)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const queryKey = useMemo(
    () => workspaceKeys.research(scope, run.id),
    [run.id, scope],
  )
  const query = useQuery({
    queryKey,
    queryFn: () => client.readAggregate(run.id),
  })
  const aggregate = useMemo(
    () => query.data ? adaptWorkbenchAggregate(query.data) : null,
    [query.data],
  )

  const submit = useCallback(async <C extends PreviewCommand>(
    command: C,
    input: ResearchV3RequestInput<C>,
  ) => {
    if (!PREVIEW_COMMANDS.has(command) || pendingCommand) return
    setPendingCommand(command)
    setMutationError(null)
    try {
      const request = buildResearchV3Request(run.id, command, input)
      await client.mutate(
        run.id,
        command,
        researchV3IdempotencyKey(command, request),
        request,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey, exact: true }),
        queryClient.invalidateQueries({ queryKey: workspaceKeys.run(scope, run.id), exact: true }),
      ])
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : 'Preview mutation failed')
    } finally {
      setPendingCommand(null)
    }
  }, [client, pendingCommand, queryClient, queryKey, run.id, scope])

  if (query.isLoading) {
    return <ResearchWorkbench status="loading" />
  }
  if (query.isError || !aggregate) {
    return (
      <ResearchWorkbench
        status="error"
        errorMessage={query.error instanceof Error ? query.error.message : '研究预览暂时无法读取。'}
        actions={{ onRetryLoad: () => { void query.refetch() } }}
      />
    )
  }

  const stateVersion = query.data?.workflow.state_version ?? 0
  const selectedPlan = query.data?.selected_plan
  const alternateCandidate = selectedPlan?.payload.candidate_id === 'depth' ? 'speed' : 'depth'
  const actions = pendingCommand ? {} : {
    onClarificationSubmit: (answers: Readonly<Record<string, string>>) => {
      void submit('clarify', {
        expected_state_version: stateVersion,
        answers: Object.entries(answers).map(([question_key, answer]) => ({ question_key, answer })),
      })
    },
    onCandidateSelect: (candidateId: 'depth' | 'speed') => {
      void submit('select_candidate', {
        expected_state_version: stateVersion,
        candidate_id: candidateId,
      })
    },
    onPlanConfirm: selectedPlan ? () => {
      void submit('confirm_plan', {
        expected_state_version: stateVersion,
        plan_version_id: selectedPlan.id,
      })
    } : undefined,
    onPlanRevise: selectedPlan ? () => {
      void submit('revise_plan', {
        expected_state_version: stateVersion,
        plan_version_id: selectedPlan.id,
        candidate_id: alternateCandidate,
        revision_note: 'User requested the alternate preview candidate.',
      })
    } : undefined,
    onRetryLoad: () => { void query.refetch() },
  }

  return (
    <section aria-label="Research V3 preview workbench" className="mt-6">
      <p className="mb-3 rounded-[10px] border border-mint-400/20 bg-mint-400/10 px-4 py-3 text-xs text-mint-200">
        Preview only · 仅生成 Requirement、ProblemGraph 与 Plan；未调用任何外部 Provider。
        {pendingCommand ? ` 正在提交 ${pendingCommand}…` : ''}
      </p>
      {mutationError ? (
        <p role="alert" className="mb-3 rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-xs text-rose">
          {mutationError}
        </p>
      ) : null}
      <ResearchWorkbench aggregate={aggregate} actions={actions} />
    </section>
  )
}
