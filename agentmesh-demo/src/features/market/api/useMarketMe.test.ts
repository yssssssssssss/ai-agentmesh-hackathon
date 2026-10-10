import { describe, expect, it } from 'vitest'
import { marketKeys } from './useMarketMe'
import { collaborationKeys } from '../../collaboration/queries'

describe('personal market query scope', () => {
  it('does not reuse another project’s cached graph or activity', () => {
    const first = { userId: 'owner', workspaceId: 'workspace', projectId: 'project-one' }
    const second = { ...first, projectId: 'project-two' }
    expect(marketKeys.me(first)).not.toEqual(marketKeys.me(second))
    expect(marketKeys.activity(first)).not.toEqual(marketKeys.activity(second))
  })

  it('does not reuse another project’s board or worker queue counts', () => {
    const first = { userId: 'owner', workspaceId: 'workspace', projectId: 'project-one' }
    const second = { ...first, projectId: 'project-two' }
    expect(collaborationKeys.marketStatus(first)).not.toEqual(collaborationKeys.marketStatus(second))
    expect(collaborationKeys.marketBoard(first)).not.toEqual(collaborationKeys.marketBoard(second))
  })
})
