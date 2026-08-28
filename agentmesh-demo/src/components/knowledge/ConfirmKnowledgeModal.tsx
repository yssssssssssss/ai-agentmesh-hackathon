import { useEffect, useRef, useState } from 'react'
import { Check, FileText } from 'lucide-react'

import type { DocumentRecord, InboxItem } from '../../features/knowledge/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'
import { Modal } from '../ui/Modal'

interface ConfirmKnowledgeModalProps {
  open: boolean
  item: InboxItem | null
  document: DocumentRecord | null
  disabled?: boolean
  loading: boolean
  onClose: () => void
  onConfirm: (text: string, expectedDocumentVersion: number) => Promise<void>
}

export function ConfirmKnowledgeModal({
  open,
  item,
  document,
  disabled = false,
  loading,
  onClose,
  onConfirm,
}: ConfirmKnowledgeModalProps) {
  const [draft, setDraft] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [draftVersion, setDraftVersion] = useState<number | null>(null)
  const initializedItemId = useRef<string | null>(null)

  useEffect(() => {
    if (!open) {
      initializedItemId.current = null
      setDraftVersion(null)
      return
    }
    if (!item?.id || !document || initializedItemId.current === item.id) return
    initializedItemId.current = item.id
    setDraft(document.text)
    setDraftVersion(document.version)
  }, [document, item?.id, open])

  const submit = async () => {
    if (draftVersion === null) return
    setSubmitting(true)
    try {
      await onConfirm(draft, draftVersion)
      onClose()
    } catch {
      // Keep the user's edit and expected version visible so a conflict can be reviewed or retried.
    } finally {
      setSubmitting(false)
    }
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="确认并沉淀新经验"
      subtitle="核对服务端保存的 Brief 正文，确认后进入团队候选记忆审核。"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button
            loading={submitting}
            disabled={disabled || loading || !document || draftVersion === null || !draft.trim()}
            icon={<Check className="h-4 w-4" />}
            onClick={() => void submit()}
          >
            确认 Brief
          </Button>
        </>
      }
    >
      {loading ? (
        <p className="text-sm text-slate-400">正在读取 Brief 正文…</p>
      ) : document ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <FileText className="h-4 w-4 text-knowledge" />
            <span className="text-sm font-medium text-slate-200">{document.title}</span>
            <Badge tone="knowledge">{item?.metadata?.artifact_type ?? 'brief_draft'}</Badge>
            <Badge tone="neutral">v{draftVersion ?? document.version}</Badge>
            <DataSourceBadge source="T" />
          </div>
          <div>
            <label htmlFor="brief-body" className="mb-2 block text-xs font-medium text-slate-400">
              Brief 正文
            </label>
            <textarea
              id="brief-body"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={14}
              className="w-full resize-y rounded-soft border border-white/[0.08] bg-surface-1 px-4 py-3 text-sm leading-6 text-slate-200 outline-none focus:border-mint-400/50"
            />
          </div>
        </div>
      ) : (
        <p role="alert" className="text-sm text-rose">Brief 文档不存在或当前账号不可见。</p>
      )}
    </Modal>
  )
}

