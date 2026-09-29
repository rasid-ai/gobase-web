import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/**
 * Status pill: the token tinted to 15% behind the token itself as text
 * (context/design-system.md).
 *
 * `neutral` is not a status token. Dagster has canceled and skipped states
 * that the four run-status tokens do not cover, and the muted foreground is
 * what the design gives them — better than inventing a fifth colour here.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium',
  {
    variants: {
      tone: {
        success: 'bg-status-success/15 text-status-success',
        running: 'bg-status-running/15 text-status-running',
        failed: 'bg-status-failed/15 text-status-failed',
        queued: 'bg-status-queued/15 text-status-queued',
        neutral: 'bg-muted-foreground/10 text-muted-foreground',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export type BadgeProps = ComponentProps<'span'> &
  VariantProps<typeof badgeVariants> & {
    /** Draw the dot as a ring rather than a disc, for inert states. */
    hollow?: boolean
  }

export function Badge({ className, tone, hollow = false, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {/*
        The dot is not decoration. Colour alone must never carry the meaning
        (context/design-system.md), so disc versus ring is a second signal on
        top of the label.
      */}
      <span
        aria-hidden="true"
        className={cn(
          'size-1.5 shrink-0 rounded-full',
          hollow ? 'border border-current' : 'bg-current',
        )}
      />
      {children}
    </span>
  )
}
