import type { AssetDetail, AssetGroup, AssetSummary } from '@/api/generated/model'
import { Button } from '@/components/ui/button'

import { useLayers } from './layers'

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
  loadingId,
}: {
  groups: readonly AssetGroup[]
  selectedId: string | null
  onSelect: (assetId: string) => void
  /** Load this asset's features onto the map. */
  onDraw: (asset: AssetSummary) => void
  /** The asset whose features are being fetched, if any. */
  loadingId: string | null
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
                  onDraw={() => onDraw(asset)}
                  loading={asset.asset_id === loadingId}
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
  loading,
}: {
  asset: AssetSummary
  selected: boolean
  onSelect: () => void
  onDraw: () => void
  loading: boolean
}) {
  const { layers } = useLayers()
  const drawn = layers.find((layer) => layer.assetId === asset.asset_id)

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

      {drawn?.truncated ? (
        <p className={`${MICRO} mt-1`}>Showing first {drawn.count} features</p>
      ) : null}
    </div>
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
function label(asset: AssetSummary): string {
  if (asset.summary) return asset.summary
  const uri = asset.source_uri ?? ''
  return uri.split('/').filter(Boolean).pop() || uri || asset.asset_id
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
}: {
  detail: AssetDetail
  onClear: () => void
}) {
  const entries = Object.entries(detail.metadata ?? {})

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <p className={MICRO}>{detail.data_type}</p>
        <span className="flex-1" />
        <Button variant="outline" size="sm" onClick={onClear}>
          Clear
        </Button>
      </div>

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
