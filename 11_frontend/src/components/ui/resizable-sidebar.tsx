import React, { useState } from 'react'

const DEFAULT_WIDTH = 320
const MIN_WIDTH = 200
const MAX_WIDTH = 720

function readWidth(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = window.localStorage.getItem(key)
    const parsed = raw ? Number(raw) : NaN
    if (Number.isFinite(parsed)) return Math.min(max, Math.max(min, parsed))
  } catch {
    // ignore
  }
  return fallback
}

type ResizableSidebarProps = {
  children: React.ReactNode
  storageKey: string
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
  'aria-label': string
  className?: string
}

export const ResizableSidebar: React.FC<ResizableSidebarProps> = ({
  children,
  storageKey,
  defaultWidth = DEFAULT_WIDTH,
  minWidth = MIN_WIDTH,
  maxWidth = MAX_WIDTH,
  'aria-label': ariaLabel,
  className = '',
}) => {
  const [width, setWidth] = useState(() => readWidth(storageKey, defaultWidth, minWidth, maxWidth))
  const widthRef = React.useRef(width)
  const drag = React.useRef<{ startX: number; startWidth: number } | null>(null)

  const persist = (next: number) => {
    try {
      window.localStorage.setItem(storageKey, String(next))
    } catch {
      // ignore
    }
  }

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    drag.current = { startX: event.clientX, startWidth: widthRef.current }
  }

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current || !Number.isFinite(event.clientX)) return
    const next = Math.min(
      maxWidth,
      Math.max(minWidth, drag.current.startWidth + (event.clientX - drag.current.startX)),
    )
    widthRef.current = next
    setWidth(next)
  }

  const onPointerUp = () => {
    if (!drag.current) return
    drag.current = null
    persist(widthRef.current)
  }

  const applyWidth = (next: number) => {
    widthRef.current = next
    setWidth(next)
    persist(next)
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 40 : 16
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      applyWidth(Math.min(maxWidth, widthRef.current + step))
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      applyWidth(Math.max(minWidth, widthRef.current - step))
    }
  }

  return (
    <div className={`flex min-h-0 shrink-0 ${className}`}>
      <section
        aria-label={ariaLabel}
        className="min-h-0 min-w-0 overflow-hidden"
        style={{ width, flexBasis: width, flexGrow: 0, flexShrink: 0 }}
      >
        {children}
      </section>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize plant tree"
        aria-valuenow={Math.round(width)}
        tabIndex={0}
        className="w-1.5 shrink-0 cursor-col-resize bg-border hover:bg-[#FF7A00] focus-visible:bg-[#FF7A00] focus-visible:outline-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
      />
    </div>
  )
}
