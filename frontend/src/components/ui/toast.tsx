import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * Transient messages for things that failed outside a form.
 *
 * Built here rather than pulled in: a toast is a list, a timer and a live
 * region, and the alternative is another Radix package for that. `Alert` stays
 * the inline, in-place version; this is the one that appears and leaves.
 */

type Toast = { id: number; message: string; tone: 'error' | 'info' }

type ToastApi = {
  /** Show a message. Returns nothing — a toast is fire-and-forget. */
  show: (message: string, tone?: Toast['tone']) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const DISMISS_AFTER_MS = 6000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(0)

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const show = useCallback(
    (message: string, tone: Toast['tone'] = 'error') => {
      const id = nextId.current++
      setToasts((current) => [...current, { id, message, tone }])
      // Timers are not cleared on unmount on purpose: the callback only drops
      // an id from a list, so a late fire after unmount is harmless.
      setTimeout(() => dismiss(id), DISMISS_AFTER_MS)
    },
    [dismiss],
  )

  const api = useMemo(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: number) => void
}) {
  return (
    // aria-live so a failure is announced without stealing focus.
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 flex-col gap-2"
    >
      {toasts.map((toast) => (
        // The outer box is solid background; the tint goes on the inner one.
        // A 10% tint alone is see-through, and over the map that made the
        // message unreadable.
        <div key={toast.id} role="status" className="pointer-events-auto rounded-md bg-background">
          <div
            className={cn(
              'flex items-start gap-3 rounded-md border px-3 py-2 text-sm',
              toast.tone === 'error'
                ? 'border-destructive/40 bg-destructive/10 text-destructive'
                : 'border-border text-foreground',
            )}
          >
            <span className="flex-1">{toast.message}</span>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss"
              className="font-mono text-[11px] uppercase tracking-[0.06em] opacity-70 hover:opacity-100"
            >
              Close
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * Show a toast.
 *
 * Outside a provider this is a no-op rather than a throw: a missing toast must
 * never be the reason a page fails to render.
 */
export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  return context ?? { show: () => {} }
}
