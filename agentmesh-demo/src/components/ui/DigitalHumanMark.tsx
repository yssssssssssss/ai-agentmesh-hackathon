import avatarUrl from '../../assets/avatar2.png'
import { cn } from '../../lib/cn'

interface DigitalHumanMarkProps {
  size?: number
  online?: boolean
  className?: string
}

/**
 * 数字人卡通头像，在线状态通过右下角状态点表达。
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
        width={size}
        height={size}
        className="h-full w-full rounded-full object-cover"
      />
      {online && (
        <span className="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-surface-1">
          <span className="h-2.5 w-2.5 rounded-full bg-mint-400 ring-2 ring-surface-1" />
        </span>
      )}
    </div>
  )
}
