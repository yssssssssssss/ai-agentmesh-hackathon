import avatarUrl from '../../assets/avatar2.png'
import { cn } from '../../lib/cn'

interface DigitalHumanMarkProps {
  size?: number
  online?: boolean
  className?: string
}

/**
 * 数字人抽象身份标识：同心环 + 核心光点，克制的轻微未来感，
 * 避免赛博朋克强发光。
 */
export function DigitalHumanMark({ size = 56, online = true, className }: DigitalHumanMarkProps) {
  return (
    <div
      className={cn('relative shrink-0', className)}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <img
        src={avatarUrl}
        alt=""
        className="absolute inset-0 h-full w-full rounded-full object-cover ring-1 ring-inset ring-white/[0.12]"
      />
      {online && (
        <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-surface-1">
          <span className="h-2.5 w-2.5 rounded-full bg-mint-400 ring-2 ring-surface-1" />
        </span>
      )}
    </div>
  )
}
