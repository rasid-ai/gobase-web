import { keepPreviousData } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'

import { useCatalogSimilarAssets } from '@/api/generated/catalog/catalog'
import type { AssetDetail, SimilarAsset } from '@/api/generated/model'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { OpenPdf } from '@/features/catalog/OpenPdf'
import { cn } from '@/lib/utils'

import { AssetDetailPanel, AssetRow, Failed } from './AssetPanel'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/** A row's own action: mono, like the Draw beside it. */
const ACTION =
  'shrink-0 rounded font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

/** How many matches one question lists. The best few, not a page. */
export const MATCHES = 10

/**
 * The right-hand pane in Semantic mode: a question, and the assets closest to
 * it in meaning (docs/adr/018).
 *
 * The question is sent once, on submit — an embedding round trip per keystroke
 * is the wrong shape — and the matches come back ranked, best first, from the
 * catalog's cards. Each row is the same row the point and area lists use —
 * Details and Draw — naming its dataset, with Open beside Draw for a document
 * whose PDF the catalog records. The detail level is the same panel as
 * everywhere else.
 *
 * The page keeps the question, so switching modes and back finds the matches
 * where they were.
 */
export function SemanticPane({
  question,
  onAsk,
  selected,
  selectedId,
  onSelect,
  onDraw,
}: {
  question: string
  onAsk: (question: string) => void
  selected: AssetDetail | null
  selectedId: string | null
  onSelect: (assetId: string | null) => void
  /** Load this asset's features onto the map. */
  onDraw: (assetId: string, name: string) => void
}) {
  const [text, setText] = useState(question)
  const [expanded, setExpanded] = useState(false)

  const matches = useCatalogSimilarAssets(
    { q: question, limit: MATCHES },
    {
      query: {
        enabled: question !== '',
        // A refused or unavailable service is the answer; asking again on
        // the user's behalf would only spend more embeddings on it.
        retry: false,
        placeholderData: keepPreviousData,
      },
    },
  )

  const answer = matches.data
  const found = answer?.status === 200 ? answer.data.results : []
  // 503 is the service not being there — not configured, or down — which is
  // a state to name, not a failure to retry.
  const unavailable = answer?.status === 503
  const failed = matches.isError || (answer !== undefined && answer.status !== 200 && !unavailable)

  function submit(event: FormEvent) {
    event.preventDefault()
    onAsk(text.trim())
  }

  return (
    <aside
      aria-label={selected ? 'Selected asset' : 'Semantic search'}
      className={cn(
        'pointer-events-auto flex min-h-0 flex-1 flex-col overflow-y-auto rounded-lg border border-border bg-background/95 p-4 backdrop-blur transition-[width]',
        selected && expanded ? 'w-[min(48rem,100%)]' : 'w-[22rem]',
      )}
    >
      {selected ? (
        <AssetDetailPanel
          detail={selected}
          expanded={expanded}
          onExpand={setExpanded}
          onClear={() => onSelect(null)}
          onDraw={onDraw}
        />
      ) : null}

      {/* Hidden, not unmounted, behind a detail: the question and the scroll stay. */}
      <div hidden={selected !== null} className="flex min-h-0 flex-col gap-3">
        <form onSubmit={submit} aria-label="Search by meaning" className="flex flex-col gap-2">
          <label htmlFor="semantic-question" className={MICRO}>
            Describe what you are looking for
          </label>
          <div className="flex gap-2">
            <Input
              id="semantic-question"
              type="search"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="A subject, a place, a kind of document…"
              maxLength={500}
              className="h-9"
            />
            <Button type="submit" variant="outline" size="sm" disabled={text.trim() === ''}>
              Search
            </Button>
          </div>
        </form>

        <Matches
          question={question}
          found={found}
          answered={answer !== undefined}
          unavailable={unavailable}
          failed={failed}
          busy={matches.isFetching}
          onRetry={() => void matches.refetch()}
          selectedId={selectedId}
          onSelect={onSelect}
          onDraw={onDraw}
        />
      </div>
    </aside>
  )
}

/** The matches, or the state standing in for them: every one explicit (context/ui-rules.md). */
function Matches({
  question,
  found,
  answered,
  unavailable,
  failed,
  busy,
  onRetry,
  selectedId,
  onSelect,
  onDraw,
}: {
  question: string
  found: readonly SimilarAsset[]
  answered: boolean
  unavailable: boolean
  failed: boolean
  busy: boolean
  onRetry: () => void
  selectedId: string | null
  onSelect: (assetId: string | null) => void
  onDraw: (assetId: string, name: string) => void
}) {
  if (question === '') {
    return (
      <p className="text-sm text-muted-foreground">
        The assets closest in meaning to what you describe are listed here.
      </p>
    )
  }
  if (unavailable) {
    return <p className="text-sm text-muted-foreground">Semantic search is unavailable.</p>
  }
  if (failed) {
    return <Failed what="Matches" onRetry={onRetry} />
  }
  if (!answered) {
    return (
      <div role="status" aria-label="Loading matches" className="flex flex-col gap-1">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-12 w-full" />
        ))}
      </div>
    )
  }
  if (found.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing matches that.</p>
  }

  return (
    <>
      <p className={MICRO}>Matches · {found.length}</p>
      <ul className={cn('flex flex-col gap-1 transition-opacity', busy && 'opacity-60')}>
        {found.map((match) => (
          <li key={match.asset_id}>
            <AssetRow
              asset={match}
              selected={match.asset_id === selectedId}
              onSelect={() => onSelect(match.asset_id)}
              onDraw={() => onDraw(match.asset_id, match.name)}
              showDataset
            >
              {/*
                Open, beside Draw, only when the catalog records the PDF:
                offered and broken is worse than not offered.
              */}
              {match.document?.pdf ? (
                <OpenPdf assetId={match.asset_id} label="Open" className={ACTION} />
              ) : null}
            </AssetRow>
          </li>
        ))}
      </ul>
    </>
  )
}
