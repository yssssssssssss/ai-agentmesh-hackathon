import { cn } from '../../lib/cn'

interface AvatarProps {
  name: string
  size?: 'sm' | 'md' | 'lg'
  tone?: 'mint' | 'knowledge' | 'collab' | 'remind'
  className?: string
}

const SIZES = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-12 w-12 text-base',
}

const TONES = {
  mint: 'bg-mint-400/15 text-mint-200 ring-mint-400/25',
  knowledge: 'bg-knowledge/15 text-knowledge ring-knowledge/25',
  collab: 'bg-collab/15 text-collab ring-collab/25',
  remind: 'bg-remind/15 text-remind ring-remind/25',
}

/** 用姓名首字生成的头像占位 */
export function Avatar({ name, size = 'md', tone = 'knowledge', className }: AvatarProps) {
  const initial = name.trim().slice(0, 1)
  return (
    <span
      className={cn(
        'inline-flex select-none items-center justify-center rounded-full font-semibold ring-1 ring-inset',
        SIZES[size],
        TONES[tone],
        className,
      )}
    >
      {initial}
    </span>
  )
}
