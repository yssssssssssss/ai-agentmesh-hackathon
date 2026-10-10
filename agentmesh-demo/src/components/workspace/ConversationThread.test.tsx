import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { ChatMessage } from '../../features/workspace/types'
import { ConversationThread } from './ConversationThread'

const messages: ChatMessage[] = [
  {
    id: 'message-user',
    thread_id: 'thread-layout',
    role: 'user',
    content: '用户消息',
    scope: 'private',
    sources: [],
  },
  {
    id: 'message-assistant',
    thread_id: 'thread-layout',
    role: 'assistant',
    content: '助手消息',
    scope: 'private',
    sources: [],
  },
]

describe('ConversationThread layout', () => {
  it.each([
    ['demo', '演示样本', true],
    ['real', '真实资料', false],
    [null, '未标注', false],
  ] as const)('shows the evidence type for %s independently of model success', (dataMode, label, warning) => {
    const html = renderToStaticMarkup(
      <ConversationThread
        messages={[{
          ...messages[1],
          workflow_trace: {
            intent: 'request_external_research', confidence: 1, source: 'skill',
            selected_workflow: '$research.request', persisted: true, llm_used: true,
            provider_mode: 'fallback', data_mode: dataMode, outcome: 'success',
          },
        }]}
        tracesByAssistantMessageId={new Map()}
        pending={null}
        loading={false}
        onOpenSource={vi.fn()}
      />,
    )

    expect(html).toContain(label)
    expect(html).toContain('查询完成')
    expect(html.includes('演示样本，不能作为真实查询依据。')).toBe(warning)
  })

  it('uses one width rule for user, assistant, and pending message bubbles', () => {
    const html = renderToStaticMarkup(
      <ConversationThread
        messages={messages}
        tracesByAssistantMessageId={new Map()}
        pending={{ content: '待发送消息', status: 'sending' }}
        loading={false}
        onOpenSource={vi.fn()}
      />,
    )
    const sharedWidthClass = 'max-w-[calc(100%_-_3rem)]'

    expect(html.split(sharedWidthClass)).toHaveLength(4)
    expect(html).not.toContain('max-w-[85%]')
    expect(html).not.toContain('max-w-[92%]')
  })

  it('renders assistant Markdown while preserving user input as literal text', () => {
    const markdownMessages: ChatMessage[] = [
      { ...messages[0], content: '# 用户原始输入' },
      { ...messages[1], content: '## 助手小结\n\n- 第一项\n- 第二项' },
    ]
    const html = renderToStaticMarkup(
      <ConversationThread
        messages={markdownMessages}
        tracesByAssistantMessageId={new Map()}
        pending={null}
        loading={false}
        onOpenSource={vi.fn()}
      />,
    )

    expect(html).toContain('# 用户原始输入')
    expect(html).toContain('<h2')
    expect(html).toContain('>助手小结</h2>')
    expect(html).toContain('<ul>')
  })
})
