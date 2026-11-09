import { ArrowUpRight, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

import type { DocumentPassages, Passage } from '@/api/generated/model'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

import { ACTION, AssetCard, MICRO } from './AssetCard'
import { OpenPdf } from './OpenPdf'
import { PagePreview } from './PagePreview'

/**
 * The deep search's answer: the documents whose passages best match the
 * question, each with those passages under its name (docs/adr/020). A ranked
 * list in one column, not the browse grid: a passage is a line of prose, and
 * three columns would fold every one. Every state is explicit
 * (context/ui-rules.md). No score is shown anywhere; the order carries the
 * ranking (docs/adr/018).
 */
export function PassagesBody({
  pending,
  status,
  results,
  inDataset,
  onRetry,
}: {
  pending: boolean
  status: number | undefined
  results: readonly DocumentPassages[]
  /** Inside one dataset, where every card would name the same dataset. */
  inDataset: boolean
  onRetry: () => void
}) {
  if (pending) {
    return (
      <div className={LIST} aria-busy="true" aria-label="Loading passages">
        {[0, 1, 2].map((card) => (
          <DocumentSkeleton key={card} />
        ))}
      </div>
    )
  }
  // 503 is the service not being there — not configured, or down — which is a
  // state to name, not a failure to retry.
  if (status === 503) {
    return (
      <Empty
        title="Semantic search is unavailable"
        detail="The service that reads documents by meaning cannot be reached."
      />
    )
  }
  if (status !== 200) {
    return (
      <div className={cn(BOX, 'flex flex-col items-center gap-3')}>
        <p className="text-sm font-medium">The catalog could not be loaded.</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    )
  }
  if (results.length === 0) {
    return (
      <Empty
        title={
          inDataset
            ? 'No passages in this dataset match that question'
            : 'No passages match that question'
        }
        detail="Change the question, or clear it."
      />
    )
  }

  return (
    <ul className={LIST}>
      {results.map((document) => (
        <li key={document.asset_id}>
          <AssetCard asset={document} showDataset={!inDataset}>
            <ul className="flex flex-col divide-y divide-border border-t border-border">
              {document.passages.map((passage) => (
                <li key={passage.chunk_id}>
                  <PassageRow
                    assetId={document.asset_id}
                    name={document.name}
                    passage={passage}
                    canOpen={document.document?.pdf ?? false}
                  />
                </li>
              ))}
            </ul>
          </AssetCard>
        </li>
      ))}
    </ul>
  )
}

/** One column, as wide as a line of prose should be and no wider. */
const LIST = 'flex max-w-[960px] flex-col gap-3.5'

const BOX = 'rounded-lg border border-border px-5 py-12 text-center'

/** The page gutter: the passage's pages and kind, read down the left edge. */
const GUTTER = 'w-[88px] shrink-0'

function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className={BOX}>
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </div>
  )
}

/** The shape of a document card with three passages, while the answer is read. */
function DocumentSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-3.5 py-3">
        <Skeleton className="h-2.5 w-16" />
        <Skeleton className="h-2.5 w-8" />
      </div>
      <div className="flex flex-col gap-2 px-3.5 py-3.5">
        <Skeleton className="h-2.5 w-28" />
        <Skeleton className="h-3 w-64" />
        <Skeleton className="h-2.5 w-20" />
      </div>
      <div className="divide-y divide-border border-t border-border">
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex gap-4 px-3.5 py-3">
            <div className={cn(GUTTER, 'flex flex-col gap-1.5')}>
              <Skeleton className="h-2.5 w-12" />
              <Skeleton className="h-2.5 w-8" />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-2.5 w-40" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-border px-3.5 py-3">
        <Skeleton className="h-2.5 w-20" />
      </div>
    </div>
  )
}

/** Where a passage is: "p. 3", or "pp. 3–4" when it runs on. */
export function formatPassagePages(passage: Passage): string | null {
  if (passage.page_start == null) return null
  if (passage.page_end != null && passage.page_end !== passage.page_start) {
    return `pp. ${passage.page_start}–${passage.page_end}`
  }
  return `p. ${passage.page_start}`
}

/**
 * One matching passage: its pages and kind in the gutter, its heading path
 * and an excerpt beside them. Expanded, the excerpt becomes the whole text
 * with the way into the PDF under it, and the page it is on — the passage
 * marked — stands in a column to the right.
 *
 * The button is the gutter, the heading and the text; the page buttons, the
 * PDF action and the preview come after it, since a button holds no buttons.
 * The chevron sits at the row's corner whatever is beside it.
 */
function PassageRow({
  assetId,
  name,
  passage,
  canOpen,
}: {
  assetId: string
  name: string
  passage: Passage
  /** Whether the catalog records the PDF, and so whether it can be opened or drawn. */
  canOpen: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  // Which of the passage's pages the preview shows; the first by default.
  const [page, setPage] = useState<number | null>(passage.pages_with_boxes[0] ?? null)
  const where = formatPassagePages(passage)
  const heading = passage.heading_path.join(' › ')
  const previewing = expanded && canOpen && page !== null
  const Chevron = expanded ? ChevronUp : ChevronDown

  return (
    <div
      className={cn(
        'relative flex gap-4 px-3.5 py-3 pr-10 transition-colors',
        expanded ? 'bg-accent/30' : 'hover:bg-accent/50',
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
          className={cn(
            'flex w-full gap-4 rounded text-left',
            'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/50',
          )}
        >
          <span className={cn(GUTTER, MICRO, 'flex flex-col gap-1 pt-0.5')}>
            {where && <span>{where}</span>}
            <span>{passage.chunk_type}</span>
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            {heading && <span className="text-xs text-muted-foreground">{heading}</span>}
            <span className={cn('text-sm leading-snug', !expanded && 'line-clamp-3')}>
              {passage.text}
            </span>
          </span>
          <Chevron aria-hidden className="absolute right-3.5 top-3 size-4 text-muted-foreground" />
        </button>

        {expanded && canOpen ? (
          <div className="mt-2 flex gap-4">
            <div className={GUTTER}>
              {passage.pages_with_boxes.length > 1 ? (
                <div role="group" aria-label="Preview page" className="flex flex-wrap gap-1">
                  {passage.pages_with_boxes.map((candidate) => (
                    <button
                      key={candidate}
                      type="button"
                      aria-pressed={candidate === page}
                      aria-label={`Page ${candidate}`}
                      onClick={() => setPage(candidate)}
                      className={cn(
                        'h-6 min-w-6 rounded border px-1 font-mono text-[11px]',
                        'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
                        candidate === page
                          ? 'border-primary bg-primary/15 text-primary'
                          : 'border-border text-muted-foreground hover:text-foreground',
                      )}
                    >
                      {candidate}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            {passage.page_start != null ? (
              <OpenPdf
                assetId={assetId}
                page={page ?? passage.page_start}
                label={`Open PDF at p. ${page ?? passage.page_start}`}
                icon={<ArrowUpRight aria-hidden className="size-3" />}
                className={cn(ACTION, 'inline-flex items-center gap-0.5 disabled:opacity-60')}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      {previewing ? (
        <div className="w-[34%] max-w-[300px] shrink-0">
          <PagePreview assetId={assetId} name={name} page={page} chunkId={passage.chunk_id} />
        </div>
      ) : null}
    </div>
  )
}
