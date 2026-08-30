import { describe, expect, it } from 'vitest'

import { conversationThreadHref } from './ConversationNav'

describe('conversation thread navigation', () => {
  it('keeps the explicit Run when reopening the active thread', () => {
    expect(conversationThreadHref('thread-1', 'thread-1', '?run=run%2Fdeepsearch-1')).toBe(
      '/workspace/thread/thread-1?run=run%2Fdeepsearch-1',
    )
  })

  it('does not carry a Run into another thread', () => {
    expect(conversationThreadHref('thread-2', 'thread-1', '?run=run-deepsearch-1')).toBe(
      '/workspace/thread/thread-2',
    )
  })
})
