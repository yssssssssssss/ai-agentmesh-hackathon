import { QueryClient, QueryObserver } from '@tanstack/react-query'
import { expect, it } from 'vitest'

import { queryKeys } from '../../app/queryKeys'
import { refreshTaskData } from './queries'

it('refreshes a newly created task even while its initial cards request is still pending', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const key = [...queryKeys.tasks.root, 'pending-cards']
  let finishInitial: (value: { version: number }) => void = () => {}
  const initialResponse = new Promise<{ version: number }>((resolve) => { finishInitial = resolve })
  let calls = 0
  const observer = new QueryObserver(client, {
    queryKey: key,
    queryFn: () => ++calls === 1 ? initialResponse : Promise.resolve({ version: 2 }),
  })
  const unsubscribe = observer.subscribe(() => {})
  expect(calls).toBe(1)

  try {
    const refreshed = refreshTaskData(client, async () => {})
    // The transport ignores cancellation, like the legacy cards API. Its late
    // response represents a snapshot taken before the successful mutation.
    await new Promise((resolve) => setTimeout(resolve, 0))
    finishInitial({ version: 1 })
    await refreshed
    expect(calls).toBe(2)
    expect(client.getQueryData(key)).toEqual({ version: 2 })
  } finally {
    unsubscribe()
    client.clear()
  }
})
