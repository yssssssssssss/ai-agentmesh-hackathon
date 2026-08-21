import {
  Check,
  Ellipsis,
  Pencil,
  Pin,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
} from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router-dom'

import {
  useDeleteThreadMutation,
  useThreadsQuery,
  useUpdateThreadMutation,
  useWorkspaceScope,
  workspaceErrorMessage,
} from '../../features/workspace/queries'
import type { ChatThread } from '../../features/workspace/types'
import { cn } from '../../lib/cn'
import { useDemo } from '../../store/DemoContext'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'

const MENU_WIDTH = 152
const MENU_HEIGHT = 124
const MENU_GAP = 5
const VIEWPORT_PADDING = 8

interface MenuPosition {
  left: number
  top: number
}

interface ThreadTarget {
  id: string
  title: string
  pinned: boolean
}

interface ThreadActionsMenuProps {
  thread: ThreadTarget
  position: MenuPosition
  menuRef: RefObject<HTMLDivElement>
  onClose: (restoreFocus?: boolean) => void
  onPin: () => void
  onRename: () => void
  onDelete: () => void
}

function activeThreadId(pathname: string): string | null {
  const encoded = pathname.match(/^\/workspace\/thread\/([^/]+)$/)?.[1]
  if (!encoded) return null
  try {
    return decodeURIComponent(encoded)
  } catch {
    return null
  }
}

function placeMenu(trigger: DOMRect): MenuPosition {
  const left = Math.min(
    window.innerWidth - MENU_WIDTH - VIEWPORT_PADDING,
    Math.max(VIEWPORT_PADDING, trigger.right - MENU_WIDTH),
  )
  const below = trigger.bottom + MENU_GAP
  const top = below + MENU_HEIGHT <= window.innerHeight - VIEWPORT_PADDING
    ? below
    : Math.max(VIEWPORT_PADDING, trigger.top - MENU_HEIGHT - MENU_GAP)
  return { left, top }
}

function focusMenuItem(event: KeyboardEvent<HTMLDivElement>) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  const items = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'),
  )
  if (items.length === 0) return
  event.preventDefault()
  const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement)
  if (event.key === 'Home') items[0].focus()
  else if (event.key === 'End') items[items.length - 1].focus()
  else if (event.key === 'ArrowDown') items[(currentIndex + 1) % items.length].focus()
  else items[(currentIndex - 1 + items.length) % items.length].focus()
}

function ThreadActionsMenu({
  thread,
  position,
  menuRef,
  onClose,
  onPin,
  onRename,
  onDelete,
}: ThreadActionsMenuProps) {
  if (typeof document === 'undefined') return null
  const itemClass = 'flex h-9 w-full items-center gap-2 rounded-[8px] px-2.5 text-left text-[13px] '
    + 'transition-[background-color,color,transform] duration-100 active:scale-[0.96] '
    + 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50'

  return createPortal(
    <div
      ref={menuRef}
      id={`thread-actions-${thread.id}`}
      role="menu"
      aria-label={`任务操作：${thread.title}`}
      style={position}
      className="fixed z-[70] w-[152px] rounded-[12px] border border-white/[0.10] bg-surface-3 p-1.5 shadow-pop"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          onClose(true)
          return
        }
        focusMenuItem(event)
      }}
    >
      <button
        type="button"
        role="menuitem"
        onClick={onPin}
        className={cn(itemClass, 'text-slate-200 hover:bg-white/[0.06] hover:text-white')}
      >
        <Pin className={cn('h-4 w-4', thread.pinned && 'fill-current text-mint-300')} aria-hidden="true" />
        {thread.pinned ? '取消置顶' : '置顶'}
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onRename}
        className={cn(itemClass, 'text-slate-200 hover:bg-white/[0.06] hover:text-white')}
      >
        <Pencil className="h-4 w-4" aria-hidden="true" />
        重命名
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onDelete}
        className={cn(itemClass, 'text-rose hover:bg-rose/10')}
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
        删除
      </button>
    </div>,
    document.body,
  )
}

function toTarget(thread: ChatThread): ThreadTarget | null {
  if (!thread.id) return null
  return { id: thread.id, title: thread.title, pinned: Boolean(thread.pinned) }
}

export function ConversationNav() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { showToast } = useDemo()
  const scope = useWorkspaceScope()
  const threads = useThreadsQuery(scope)
  const updateThread = useUpdateThreadMutation(scope)
  const deleteThread = useDeleteThreadMutation(scope)
  const activeId = activeThreadId(pathname)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [deletingThread, setDeletingThread] = useState<ThreadTarget | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuTriggerRef = useRef<HTMLButtonElement | null>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)

  const closeMenu = (restoreFocus = false) => {
    setOpenMenuId(null)
    setMenuPosition(null)
    if (restoreFocus) menuTriggerRef.current?.focus()
  }

  useEffect(() => {
    if (!openMenuId) return
    const focusFrame = window.requestAnimationFrame(() => {
      menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
    })
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (menuRef.current?.contains(target) || menuTriggerRef.current?.contains(target)) return
      closeMenu()
    }
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu(true)
    }
    const closeForLayoutChange = () => closeMenu()
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleEscape)
    window.addEventListener('resize', closeForLayoutChange)
    window.addEventListener('scroll', closeForLayoutChange, true)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleEscape)
      window.removeEventListener('resize', closeForLayoutChange)
      window.removeEventListener('scroll', closeForLayoutChange, true)
    }
  }, [openMenuId])

  useEffect(() => {
    closeMenu()
  }, [pathname])

  useEffect(() => {
    if (!renamingId) return
    renameInputRef.current?.focus()
    renameInputRef.current?.select()
  }, [renamingId])

  const menuThread = threads.data?.items
    .map(toTarget)
    .find((thread): thread is ThreadTarget => thread?.id === openMenuId) ?? null

  const openMenu = (event: MouseEvent<HTMLButtonElement>, thread: ThreadTarget) => {
    if (openMenuId === thread.id) {
      closeMenu(true)
      return
    }
    menuTriggerRef.current = event.currentTarget
    setMenuPosition(placeMenu(event.currentTarget.getBoundingClientRect()))
    setOpenMenuId(thread.id)
    setActionError(null)
  }

  const togglePin = async (thread: ThreadTarget) => {
    closeMenu(true)
    setActionError(null)
    try {
      await updateThread.mutateAsync({ threadId: thread.id, update: { pinned: !thread.pinned } })
      showToast(thread.pinned ? `已取消置顶「${thread.title}」` : `已置顶「${thread.title}」`)
    } catch (error) {
      setActionError(workspaceErrorMessage(error))
    }
  }

  const beginRename = (thread: ThreadTarget) => {
    closeMenu()
    setActionError(null)
    setRenameDraft(thread.title)
    setRenamingId(thread.id)
  }

  const submitRename = async (event: FormEvent<HTMLFormElement>, thread: ThreadTarget) => {
    event.preventDefault()
    const title = renameDraft.trim()
    if (!title) {
      setActionError('任务名称不能为空')
      return
    }
    if (title === thread.title) {
      setRenamingId(null)
      return
    }
    setActionError(null)
    try {
      await updateThread.mutateAsync({ threadId: thread.id, update: { title } })
      setRenamingId(null)
      showToast(`已重命名为「${title}」`)
    } catch (error) {
      setActionError(workspaceErrorMessage(error))
    }
  }

  const beginDelete = (thread: ThreadTarget) => {
    closeMenu()
    setActionError(null)
    setDeletingThread(thread)
  }

  const closeDelete = () => {
    if (deleteThread.isPending) return
    setDeletingThread(null)
    setActionError(null)
  }

  const confirmDelete = async () => {
    if (!deletingThread) return
    const target = deletingThread
    setActionError(null)
    try {
      await deleteThread.mutateAsync(target.id)
      setDeletingThread(null)
      if (activeId === target.id) navigate('/workspace')
      showToast(`已删除「${target.title}」`, 'info')
    } catch (error) {
      setActionError(workspaceErrorMessage(error))
    }
  }

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => navigate('/workspace')}
        className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-[13px] font-medium text-mint-300 transition-[background-color,color,transform] duration-100 hover:bg-white/[0.04] hover:text-mint-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
      >
        <Plus className="h-4 w-4 shrink-0" aria-hidden="true" />
        开始新对话
      </button>

      {threads.isLoading ? <p className="px-2.5 py-2 text-xs text-slate-500">正在加载对话…</p> : null}
      {threads.isError ? (
        <p role="alert" className="px-2.5 py-2 text-xs leading-5 text-rose">
          {workspaceErrorMessage(threads.error)}
        </p>
      ) : null}
      {threads.data?.items.map((thread) => {
        const target = toTarget(thread)
        if (!target) return null
        const isActive = target.id === activeId
        const isRenaming = target.id === renamingId
        return (
          <div
            key={target.id}
            data-testid="conversation-task"
            data-thread-id={target.id}
            className={cn(
              'group flex min-h-8 w-full items-center rounded-[8px] transition-colors duration-100',
              isActive
                ? 'bg-surface-3 font-medium text-slate-100'
                : 'text-slate-300 hover:bg-white/[0.04]',
            )}
          >
            {isRenaming ? (
              <form
                className="flex min-w-0 flex-1 items-center gap-1 p-1"
                onSubmit={(event) => void submitRename(event, target)}
              >
                <input
                  ref={renameInputRef}
                  aria-label={`重命名任务：${target.title}`}
                  value={renameDraft}
                  maxLength={200}
                  disabled={updateThread.isPending}
                  onChange={(event) => setRenameDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key !== 'Escape') return
                    event.preventDefault()
                    setRenamingId(null)
                    setActionError(null)
                  }}
                  className="h-7 min-w-0 flex-1 rounded-[6px] border border-mint-400/45 bg-base px-2 text-[12px] text-slate-100 outline-none focus:border-mint-300 focus:ring-2 focus:ring-mint-400/20 disabled:opacity-60"
                />
                <button
                  type="submit"
                  aria-label="保存任务名称"
                  disabled={updateThread.isPending || !renameDraft.trim()}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] text-mint-300 transition-[background-color,color,transform] duration-100 hover:bg-mint-400/10 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 disabled:opacity-40"
                >
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label="取消重命名"
                  disabled={updateThread.isPending}
                  onClick={() => {
                    setRenamingId(null)
                    setActionError(null)
                  }}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] text-slate-500 transition-[background-color,color,transform] duration-100 hover:bg-white/[0.05] hover:text-slate-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 disabled:opacity-40"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </form>
            ) : (
              <>
                <button
                  type="button"
                  aria-label={target.title}
                  aria-current={isActive ? 'page' : undefined}
                  onClick={() => navigate(`/workspace/thread/${encodeURIComponent(target.id)}`)}
                  className="min-w-0 flex-1 truncate rounded-l-[8px] px-2.5 py-1.5 text-left text-xs leading-snug focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-mint-400/50"
                >
                  {target.title}
                </button>
                {target.pinned ? (
                  <Pin className="h-3 w-3 shrink-0 fill-current text-mint-300" aria-label="已置顶" />
                ) : null}
                <button
                  type="button"
                  aria-label={`更多任务操作：${target.title}`}
                  aria-haspopup="menu"
                  aria-expanded={openMenuId === target.id}
                  aria-controls={openMenuId === target.id ? `thread-actions-${target.id}` : undefined}
                  onClick={(event) => openMenu(event, target)}
                  className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] text-slate-600 opacity-70 transition-[background-color,color,opacity,transform] duration-100 hover:bg-white/[0.06] hover:text-slate-200 hover:opacity-100 active:scale-[0.96] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 group-hover:opacity-100"
                >
                  <Ellipsis className="h-4 w-4" aria-hidden="true" />
                </button>
              </>
            )}
          </div>
        )
      })}
      {actionError && !deletingThread ? (
        <p role="alert" className="px-2.5 py-2 text-xs leading-5 text-rose">{actionError}</p>
      ) : null}

      {menuThread && menuPosition ? (
        <ThreadActionsMenu
          thread={menuThread}
          position={menuPosition}
          menuRef={menuRef}
          onClose={closeMenu}
          onPin={() => void togglePin(menuThread)}
          onRename={() => beginRename(menuThread)}
          onDelete={() => beginDelete(menuThread)}
        />
      ) : null}

      <Modal
        open={Boolean(deletingThread)}
        onClose={closeDelete}
        title="删除任务？"
        subtitle="该操作会将任务及其对话从 AI 工作台历史中移除。"
        footer={
          <>
            <Button variant="ghost" disabled={deleteThread.isPending} onClick={closeDelete}>取消</Button>
            <Button
              variant="danger"
              loading={deleteThread.isPending}
              icon={<Trash2 className="h-4 w-4" />}
              onClick={() => void confirmDelete()}
            >
              删除任务
            </Button>
          </>
        }
      >
        <p className="rounded-[10px] border border-white/[0.06] bg-surface-1 px-4 py-3 text-sm text-slate-200">
          {deletingThread?.title}
        </p>
        {actionError ? <p role="alert" className="mt-3 text-sm text-rose">{actionError}</p> : null}
      </Modal>
    </div>
  )
}
