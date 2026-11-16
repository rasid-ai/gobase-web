import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** Placeholder block for a data view that has not answered yet. */
export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div className={cn('animate-pulse rounded-md bg-muted-foreground/10', className)} {...props} />
  )
}
