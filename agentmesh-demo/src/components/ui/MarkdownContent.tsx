import Markdown, { type MarkdownToJSX } from 'markdown-to-jsx/react'
import { Fragment, type ComponentPropsWithoutRef } from 'react'

import { cn } from '../../lib/cn'

function MarkdownLink({ href, children, ...props }: ComponentPropsWithoutRef<'a'>) {
  const external = Boolean(href && /^(?:https?:)?\/\//.test(href))
  return (
    <a {...props} href={href} target={external ? '_blank' : undefined} rel={external ? 'noreferrer' : undefined}>
      {children}
    </a>
  )
}

const MARKDOWN_OPTIONS: MarkdownToJSX.Options = {
  disableParsingRawHTML: true,
  enforceAtxHeadings: true,
  forceBlock: true,
  wrapper: Fragment,
  overrides: {
    a: { component: MarkdownLink },
  },
}

interface MarkdownContentProps {
  content: string
  className?: string
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div
      className={cn(
        'min-w-0 break-words text-sm leading-7 text-slate-300',
        '[&>*:first-child]:mt-0 [&>*:last-child]:mb-0',
        '[&_h1]:mb-3 [&_h1]:mt-6 [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:leading-7 [&_h1]:text-slate-100',
        '[&_h2]:mb-2 [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:leading-7 [&_h2]:text-slate-100',
        '[&_h3]:mb-2 [&_h3]:mt-5 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-slate-100',
        '[&_h4]:mb-2 [&_h4]:mt-5 [&_h4]:text-sm [&_h4]:font-semibold [&_h4]:text-slate-200',
        '[&_h5]:mb-2 [&_h5]:mt-4 [&_h5]:text-sm [&_h5]:font-medium [&_h5]:text-slate-200',
        '[&_h6]:mb-2 [&_h6]:mt-4 [&_h6]:text-xs [&_h6]:font-semibold [&_h6]:text-slate-400',
        '[&_p]:my-3',
        '[&_ul]:my-3 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5',
        '[&_ol]:my-3 [&_ol]:list-decimal [&_ol]:space-y-1 [&_ol]:pl-5',
        '[&_li]:pl-1 [&_li>p]:my-1',
        '[&_strong]:font-semibold [&_strong]:text-slate-100',
        '[&_a]:break-words [&_a]:text-mint-300 [&_a]:underline [&_a]:decoration-mint-400/30 [&_a]:underline-offset-4',
        '[&_blockquote]:my-4 [&_blockquote]:rounded-soft [&_blockquote]:bg-white/[0.04] [&_blockquote]:px-4 [&_blockquote]:py-2 [&_blockquote]:text-slate-400',
        '[&_code]:rounded-control [&_code]:bg-white/[0.06] [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.9em] [&_code]:text-mint-200',
        '[&_pre]:my-4 [&_pre]:overflow-x-auto [&_pre]:rounded-soft [&_pre]:bg-base [&_pre]:p-4 [&_pre]:text-xs [&_pre]:leading-6',
        '[&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-slate-300',
        '[&_hr]:my-6 [&_hr]:border-white/[0.08]',
        '[&_table]:my-4 [&_table]:block [&_table]:w-full [&_table]:overflow-x-auto [&_table]:border-collapse [&_table]:text-left [&_table]:text-xs',
        '[&_th]:border [&_th]:border-white/[0.08] [&_th]:bg-white/[0.04] [&_th]:px-3 [&_th]:py-2 [&_th]:font-semibold [&_th]:text-slate-200',
        '[&_td]:border [&_td]:border-white/[0.08] [&_td]:px-3 [&_td]:py-2 [&_td]:text-slate-300',
        '[&_img]:my-4 [&_img]:max-w-full [&_img]:rounded-soft',
        className,
      )}
    >
      <Markdown options={MARKDOWN_OPTIONS}>{content}</Markdown>
    </div>
  )
}
