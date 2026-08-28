import { cn } from '../../lib/utils'
import type { HTMLAttributes } from 'react'

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'inline-flex rounded border border-console-border bg-console-bg px-1.5 py-0.5 text-xs text-console-muted',
        className,
      )}
      {...props}
    />
  )
}
