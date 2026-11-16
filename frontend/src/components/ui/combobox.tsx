import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * The surface a combobox hangs beneath its input.
 *
 * Surfaces are flat (context/design-system.md): every shadow token is
 * transparent, so this separates from what is behind it by a hairline and a
 * lifted tone, never by elevation. On the map it also blurs, matching the
 * panels it sits among.
 */
export function ComboboxPopup({
  className,
  blur = false,
  children,
}: {
  className?: string
  /** For a popup over the map, where the panels are translucent. */
  blur?: boolean
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        // z-20 clears the map's docked panels at z-10 and stays under the
        // toast at z-50.
        'absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-md border border-border bg-popover',
        blur && 'bg-popover/95 backdrop-blur',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** The list itself. It holds options and nothing else. */
export function ComboboxList({
  id,
  label,
  children,
}: {
  id: string
  label: string
  children: ReactNode
}) {
  return (
    <ul id={id} role="listbox" aria-label={label} className="max-h-72 overflow-y-auto py-1">
      {children}
    </ul>
  )
}

export function ComboboxOption({
  active,
  children,
  ...option
}: {
  active: boolean
  children: ReactNode
} & Record<string, unknown>) {
  return (
    <li
      {...option}
      className={cn(
        'cursor-pointer px-2.5 py-1.5',
        // A neutral tint, the same one Skeleton uses. A highlight is not a
        // state, so it never borrows a status or map colour.
        active && 'bg-muted-foreground/10',
      )}
    >
      {children}
    </li>
  )
}

/**
 * Anything the popup says that is not an option.
 *
 * Kept out of the listbox on purpose: a message inside it could be arrowed
 * onto and "selected", which would do nothing and say nothing.
 */
export function ComboboxStatus({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="px-2.5 py-2 text-sm text-muted-foreground">
      {children}
    </p>
  )
}

/** The mono section label above a group of options. */
export function ComboboxLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-2.5 pb-1 pt-2 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
      {children}
    </p>
  )
}
