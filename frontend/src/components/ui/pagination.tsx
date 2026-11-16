import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * Numbered page control for a list the server pages by offset.
 *
 * Renders nothing when everything fits on one page: a control offering the
 * page you are already on says nothing and invites a click that does nothing.
 */
export function Pagination({
  page,
  pageCount,
  onPage,
  className,
}: {
  /** The page being shown, counted from 1. */
  page: number
  pageCount: number
  onPage: (page: number) => void
  className?: string
}) {
  if (pageCount <= 1) return null

  return (
    <nav
      aria-label="Pagination"
      className={cn('flex flex-wrap items-center justify-center gap-1', className)}
    >
      <Button variant="outline" size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>
        Previous
      </Button>

      {pageNumbers(page, pageCount).map((entry, index) =>
        entry === GAP ? (
          <span
            // Nothing to read out: the numbers either side already say pages
            // were left out.
            aria-hidden="true"
            key={`gap-${index}`}
            className="px-1 text-sm text-muted-foreground"
          >
            …
          </span>
        ) : (
          <Button
            key={entry}
            variant={entry === page ? 'primary' : 'ghost'}
            size="sm"
            className="w-8 px-0"
            aria-label={`Page ${entry}`}
            aria-current={entry === page ? 'page' : undefined}
            onClick={() => onPage(entry)}
          >
            {entry}
          </Button>
        ),
      )}

      <Button
        variant="outline"
        size="sm"
        onClick={() => onPage(page + 1)}
        disabled={page >= pageCount}
      >
        Next
      </Button>
    </nav>
  )
}

/** Stands in for the pages left out between two numbers. */
const GAP = 'gap'

/**
 * Which page numbers the control shows: the first, the last, the current one
 * and its neighbours, with a gap wherever numbers were left out.
 *
 * Near either end the window widens inwards instead of hanging off the edge,
 * so the row keeps one width and the buttons do not shift under the pointer
 * as you step through.
 */
function pageNumbers(page: number, pageCount: number): (number | typeof GAP)[] {
  const shown = new Set([1, pageCount, page - 1, page, page + 1])
  if (page <= 3) for (const near of [2, 3, 4]) shown.add(near)
  if (page >= pageCount - 2) for (const near of [1, 2, 3]) shown.add(pageCount - near)

  const numbers = [...shown]
    .filter((number) => number >= 1 && number <= pageCount)
    .sort((left, right) => left - right)

  const entries: (number | typeof GAP)[] = []
  numbers.forEach((number, index) => {
    if (index > 0 && number - numbers[index - 1] > 1) entries.push(GAP)
    entries.push(number)
  })
  return entries
}
