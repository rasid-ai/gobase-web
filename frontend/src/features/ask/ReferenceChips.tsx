import { useMapAssetDetail } from '@/api/generated/map/map'
import type { ChatReference } from '@/api/generated/model'
import { Skeleton } from '@/components/ui/skeleton'
import { openDocumentPdf } from '@/features/catalog/openDocument'
import { layerId } from '@/features/workspace/layerId'
import { useLayers } from '@/features/workspace/layers'
import { cn } from '@/lib/utils'

import {
  type Citation,
  type GroupedReferences,
  type Mark,
  layerLabel,
  layerScopeOf,
} from './references'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

const CHIP =
  'inline-flex max-w-full items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

type Label = { name: string; dataType: string }

/**
 * The asset's name and data type, for a chip.
 *
 * The agent sends them with the reference, as it read them from the catalog.
 * When a reference lacks them (an older agent, or a kind that carries only an
 * id, docs/adr/024), the chip reads the asset's detail — the same request the
 * map's panel makes when the chip is clicked, so that click is then answered
 * from the cache. An id the catalog does not have shows no chip: there is
 * nothing true to say about it.
 */
function useAssetLabel(assetId: string, known: { name: string | null; dataType: string | null }) {
  const detail = useMapAssetDetail(assetId, { query: { enabled: known.name === null } })
  if (known.name !== null) {
    return { label: { name: known.name, dataType: known.dataType ?? '' } as Label, loading: false }
  }
  const asset = detail.data?.status === 200 ? detail.data.data : null
  const missing = detail.isError || (detail.data !== undefined && detail.data.status !== 200)
  const label: Label | null = asset ? { name: asset.name, dataType: asset.data_type } : null
  return { label, loading: !label && !missing }
}

function ChipSkeleton() {
  return <Skeleton className="h-8 w-44" />
}

/**
 * A citation marker in the answer's text: its number, as a button that opens
 * the asset. The chip under the answer carries the same number.
 */
/**
 * Open what a citation names. A document opens its PDF in a new tab, at the
 * cited page; it has nothing to draw, so the map's pane is the wrong place for
 * it. Anything else, or a PDF that cannot be fetched, opens in the map's pane.
 *
 * `openDocumentPdf` opens its tab before its first await, inside the click,
 * which is what popup blockers allow, so this must be called from the click.
 */
async function openCited(
  target: { assetId: string; page: number | null; dataType: string | null },
  onSelect: (assetId: string) => void,
): Promise<void> {
  if (target.dataType === 'document') {
    if (await openDocumentPdf(target.assetId, target.page ?? undefined)) return
  }
  onSelect(target.assetId)
}

export function CitationMark({
  mark,
  onSelect,
}: {
  mark: Mark
  onSelect: (assetId: string) => void
}) {
  const label = mark.name ? `Citation ${mark.number}: ${mark.name}` : `Citation ${mark.number}`
  return (
    <button
      type="button"
      onClick={() => void openCited(mark, onSelect)}
      aria-label={label}
      title={mark.name ?? undefined}
      className="mx-0.5 inline-flex h-[1.3em] min-w-[1.3em] items-center justify-center rounded-sm border border-border bg-background px-1 align-[0.15em] font-mono text-[0.7em] leading-none text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {mark.number}
    </button>
  )
}

/**
 * A cited asset, with its number and its page for a passage. Selecting it opens
 * a document's PDF at that page, and shows anything else in the map's pane.
 */
export function CitationChip({
  citation,
  onSelect,
}: {
  citation: Citation
  onSelect: (assetId: string) => void
}) {
  const { assetId, page, number } = citation
  const { label, loading } = useAssetLabel(assetId, citation)
  if (loading) return <ChipSkeleton />
  if (!label) return null

  return (
    <button
      type="button"
      onClick={() => void openCited({ assetId, page, dataType: label.dataType }, onSelect)}
      className={CHIP}
      title={label.dataType === 'document' ? `Open the PDF of ${label.name}` : label.name}
    >
      {number !== null ? <span className={cn(MICRO, 'shrink-0')}>{number}</span> : null}
      <span className="truncate">{label.name}</span>
      <span className={cn(MICRO, 'shrink-0')}>
        {label.dataType}
        {page !== null ? ` p. ${page}` : ''}
      </span>
    </button>
  )
}

/**
 * A layer the answer put on the map, with the count it gave.
 *
 * Clicking shows or hides it. A layer from a reopened session is not on the
 * map yet, so the first click draws it. Drawing goes through the same layer
 * store as the asset panel's Draw (docs/adr/008), with the answer's own place
 * and filter, so the map shows what the count counted, not the current view.
 */
export function LayerChip({ reference }: { reference: ChatReference }) {
  const assetId = reference.asset_id!
  const { label: asset, loading } = useAssetLabel(assetId, {
    name: reference.name ?? null,
    dataType: reference.data_type ?? null,
  })
  const { layers, add, toggle } = useLayers()
  if (loading) return <ChipSkeleton />
  if (!asset) return null

  const scope = layerScopeOf(reference)
  const id = layerId(assetId, scope)
  const layer = layers.find((one) => one.id === id)
  const shown = layer?.visible ?? false
  const label = layerLabel(asset.name, reference)

  return (
    <button
      type="button"
      aria-pressed={shown}
      onClick={() => (layer ? toggle(id) : add({ id, assetId, label, scope }))}
      className={cn(CHIP, !shown && 'border-dashed text-muted-foreground')}
      title={shown ? `Hide ${label}` : `Show ${label}`}
    >
      <span
        aria-hidden="true"
        className={cn(
          'size-3 shrink-0 rounded-[2px] border border-map-result',
          shown && 'bg-map-result',
        )}
      />
      <span className="truncate">{label}</span>
      {reference.total !== null && reference.total !== undefined ? (
        <span className={cn(MICRO, 'shrink-0')}>{reference.total.toLocaleString()}</span>
      ) : null}
    </button>
  )
}

/** The citations under an answer, and "Framed to the answer" when it moved the map. */
export function Citations({
  grouped,
  onSelect,
  onFrame,
}: {
  grouped: GroupedReferences
  onSelect: (assetId: string) => void
  onFrame: (bbox: [number, number, number, number]) => void
}) {
  const { citations, frame } = grouped
  if (citations.length === 0 && !frame) return null

  return (
    <div className="flex flex-col items-start gap-2">
      {frame ? (
        <button
          type="button"
          onClick={() => onFrame(frame)}
          className="text-sm text-muted-foreground hover:text-foreground hover:underline"
          title="Frame the map on the answer again"
        >
          Framed to the answer
        </button>
      ) : null}
      {citations.map((citation) => (
        <CitationChip
          key={`${citation.assetId}:${citation.page ?? ''}`}
          citation={citation}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}

/**
 * The layers the answer put on the map. Cited assets are not repeated here:
 * each is already a numbered chip under the answer, which opens it.
 */
export function OutputBox({ grouped }: { grouped: GroupedReferences }) {
  const { layers } = grouped
  if (layers.length === 0) return null
  return (
    <section
      aria-label="What the answer found"
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
    >
      <div className="flex flex-col items-start gap-2">
        <h3 className={MICRO}>On the map · {layers.length}</h3>
        {layers.map((reference) => (
          <LayerChip
            key={layerId(reference.asset_id!, layerScopeOf(reference))}
            reference={reference}
          />
        ))}
      </div>
    </section>
  )
}
