import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * One choice out of a few, shown side by side.
 *
 * A radio group rather than tabs: choosing changes what the page lists and
 * nothing else — there are no panels to switch between. `mono` is for choices
 * that are data, such as data types; choices that are navigation stay in body
 * text (context/design-system.md).
 */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  mono = false,
  className,
}: {
  /** What the group chooses, for assistive technology. */
  label: string
  options: readonly { value: T; label: ReactNode }[]
  value: T
  onChange: (value: T) => void
  mono?: boolean
  className?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn('flex overflow-hidden rounded-md border border-border', className)}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'flex-1 px-3 py-1.5 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/50',
            mono ? 'font-mono text-[11px] uppercase tracking-[0.06em]' : 'text-sm',
            value === option.value
              ? 'bg-primary/15 text-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
