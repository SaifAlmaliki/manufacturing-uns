import { cn } from '../../lib/utils'
import type { ButtonHTMLAttributes } from 'react'

export function Button({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        'rounded border border-console-border bg-console-panel px-2 py-1 text-sm text-console-text hover:border-console-accent',
        className,
      )}
      {...props}
    />
  )
}
