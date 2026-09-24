import type { AssetDetail, AssetGroup, AssetSummary } from '@/api/generated/model'
import { Button } from '@/components/ui/button'

import { useLayers } from './layers'
import type { AssetFeatures } from './useAssetFeatures'
import { useAssetFeatures } from './useAssetFeatures'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/**
 * The assets covering a clicked point, grouped by data type.
 *
 * Groups render in the order the API returns them. The portal neither defines
 * nor sorts the data types — they come from the knowledge base.
 */
export function AssetList({
  groups,
  selectedId,
  onSelect,
  onDraw,
}: {
  groups: readonly AssetGroup[]
  selectedId: string | null
  onSelect: (assetId: string) => void
  /** Load this asset's features onto the map. */
  onDraw: (assetId: string, name: string) => void
}) {
  return (
    <div className="flex flex-col gap-5">
      {groups.map((group) => (
        <section key={group.data_type}>
          <p className={MICRO}>
            {group.data_type} · {group.assets.length}
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {group.assets.map((asset) => (
              <li key={asset.asset_id}>
                <AssetRow
                  asset={asset}
                  selected={asset.asset_id === selectedId}
                  onSelect={() => onSelect(asset.asset_id)}
                  onDraw={() => onDraw(asset.asset_id, label(asset))}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function AssetRow({
  asset,
  selected,
  onSelect,
  onDraw,
}: {
  asset: AssetSummary
  selected: boolean
  onSelect: () => void
  onDraw: () => void
}) {
  const { layers } = useLayers()
  const drawn = layers.find((layer) => layer.assetId === asset.asset_id)
  // Same asset, same area, same query key as the layer on the map: React Query
  // hands both this row and the map one answer, not two requests.
  const features = useAssetFeatures(asset.asset_id, Boolean(drawn?.visible))
  const loading = Boolean(drawn) && features.loading

  return (
    <div
      className={[
        'w-full rounded-md border px-3 py-2 text-sm',
        selected
          ? 'border-map-footprint bg-map-footprint/10'
          : 'border-border hover:border-map-footprint/60',
      ].join(' ')}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSelect}
          aria-current={selected ? 'true' : undefined}
          aria-label={`Details for ${label(asset)}`}
          className="min-w-0 flex-1 text-left"
        >
          <span className="block truncate">{label(asset)}</span>
          {asset.format ? <span className={`${MICRO} mt-0.5 block`}>{asset.format}</span> : null}
        </button>

        {/*
          Drawing is its own control, not the row click: selecting shows
          metadata, drawing puts features on the map, and one must not force
          the other (docs/adr/008).
        */}
        <button
          type="button"
          onClick={onDraw}
          disabled={loading}
          aria-label={drawn ? `Redraw ${label(asset)}` : `Draw ${label(asset)}`}
          className="shrink-0 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {loading ? <Spinner /> : drawn ? <span aria-hidden>✓</span> : 'Draw'}
        </button>
      </div>

      {drawn ? <LayerNote features={features} className="mt-1" /> : null}
    </div>
  )
}

/**
 * What a drawn layer is showing, in a line.
 *
 * Silent when the layer is simply drawn and whole — the features on the map
 * already say that. It speaks when the answer is partial, and the advice is
 * the actual fix rather than a limit to live with: a smaller area is read in
 * full. Which smaller area depends on the scope. Zooming in shrinks a window,
 * but a drawn area is fixed, so zooming in does nothing to it — there the fix
 * is to draw a smaller one.
 */
function LayerNote({ features, className }: { features: AssetFeatures; className?: string }) {
  if (features.failed) {
    return (
      <p className={`${MICRO} ${className ?? ''}`}>
        {features.notFound ? 'No vector data to draw' : 'Could not read this layer'}
      </p>
    )
  }
  if (!features.truncated) return null
  return (
    <p className={`${MICRO} ${className ?? ''}`}>
      {features.count} features shown ·{' '}
      {features.scope === 'area' ? 'draw a smaller area for the rest' : 'zoom in for the rest'}
    </p>
  )
}

function Spinner() {
  return (
    <span
      role="status"
      aria-label="Loading"
      className="block size-3 animate-spin rounded-full border border-current border-t-transparent"
    />
  )
}

/** The catalog has no display name, so the source it came from is the identity. */
function name(summary: unknown, sourceUri: unknown, assetId: string): string {
  if (typeof summary === 'string' && summary) return summary
  const uri = typeof sourceUri === 'string' ? sourceUri : ''
  return uri.split('/').filter(Boolean).pop() || uri || assetId
}

function label(asset: AssetSummary): string {
  return name(asset.summary, asset.source_uri, asset.asset_id)
}

/**
 * The same name, read out of the metadata dict.
 *
 * An asset reached from the Assets page has no catalog row here — only its
 * detail — so the two panels must agree on what an asset is called by sharing
 * the rule, not by each having one.
 */
function labelOf(detail: AssetDetail): string {
  const metadata = detail.metadata ?? {}
  return name(metadata.summary, metadata.source_uri, detail.asset_id)
}

/**
 * One asset's metadata and the control that clears it.
 *
 * The key set is not fixed and differs by data type, so nothing here is
 * hardcoded per field — an unknown key renders like any other.
 */
export function AssetDetailPanel({
  detail,
  onClear,
  onDraw,
}: {
  detail: AssetDetail
  onClear: () => void
  /** Load this asset's features onto the map. */
  onDraw: (assetId: string, name: string) => void
}) {
  const entries = Object.entries(detail.metadata ?? {})
  const { layers } = useLayers()
  const drawn = layers.find((layer) => layer.assetId === detail.asset_id)
  const features = useAssetFeatures(detail.asset_id, Boolean(drawn?.visible))
  const loading = Boolean(drawn) && features.loading

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <p className={MICRO}>{detail.data_type}</p>
        <span className="flex-1" />
        {/*
          Drawing is offered here for the same reason it is offered in the row
          above: an asset reached from the Assets page never passes through
          that list, so without this the only way to draw it would be to find
          it again by clicking the map.

          Offered whatever the data type is. Only vector assets have features
          to draw, but which types those are belongs to the knowledge base and
          not to this file (specs/map.md) — an asset with nothing to draw says
          so when asked, exactly as it does from the list.
        */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => onDraw(detail.asset_id, labelOf(detail))}
          disabled={loading}
        >
          {loading ? <Spinner /> : drawn ? 'Redraw' : 'Draw'}
        </Button>
        <Button variant="outline" size="sm" onClick={onClear}>
          Clear
        </Button>
      </div>

      {drawn ? <LayerNote features={features} /> : null}

      <dl className="flex flex-col divide-y divide-border border-y border-border">
        {entries.map(([key, value]) => (
          <div key={key} className="grid grid-cols-[minmax(0,9rem)_1fr] gap-3 py-2">
            <dt className={MICRO}>{key}</dt>
            <dd className="min-w-0 break-words font-mono text-[12px]">{render(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Scalars print as themselves; anything structured prints as JSON. */
function render(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
