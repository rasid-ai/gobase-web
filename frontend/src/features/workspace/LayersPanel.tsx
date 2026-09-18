import type { ActiveLayer } from './layers'
import { useLayers } from './layers'
import type { Bbox } from '@/features/places/bbox'
import { useAssetFeatures } from './useAssetFeatures'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/**
 * The layers drawn on the map, with the controls that manage them.
 *
 * Docked bottom-left so it never sits under the asset panel on the right or
 * the mode switch top-left. Renders nothing when no layer is loaded — an empty
 * panel would be chrome for its own sake.
 */
export function LayersPanel() {
  const { layers, toggle, remove, clear, view } = useLayers()

  if (layers.length === 0) return null

  return (
    <section
      aria-label="Active layers"
      className="absolute bottom-4 left-4 z-10 flex w-[18rem] flex-col rounded-lg border border-border bg-background/95 backdrop-blur"
    >
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className={MICRO}>Layers · {layers.length}</h2>
        <button
          type="button"
          onClick={clear}
          className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground"
        >
          Clear all
        </button>
      </header>

      <ul className="flex max-h-[14rem] flex-col overflow-y-auto">
        {layers.map((layer) => (
          <LayerRow
            key={layer.assetId}
            layer={layer}
            view={view}
            onToggle={() => toggle(layer.assetId)}
            onRemove={() => remove(layer.assetId)}
          />
        ))}
      </ul>
    </section>
  )
}

/**
 * One layer, with what it is currently showing.
 *
 * A row of its own because the count comes from a hook, and the count is per
 * area now: it is how many features are on the map right now, not how big the
 * file is. `+` means the area holds more than the budget read.
 */
function LayerRow({
  layer,
  view,
  onToggle,
  onRemove,
}: {
  layer: ActiveLayer
  view: Bbox | null
  onToggle: () => void
  onRemove: () => void
}) {
  const features = useAssetFeatures(layer.assetId, view, layer.visible)

  return (
    <li className="flex items-center gap-2 border-b border-border/60 px-3 py-2 last:border-b-0">
      <input
        type="checkbox"
        checked={layer.visible}
        onChange={onToggle}
        aria-label={`Show ${layer.label}`}
        className="accent-map-result"
      />
      <span className="flex-1 truncate text-sm" title={layer.label}>
        {layer.label}
      </span>
      <span className={MICRO} title="Features in view">
        {features.failed ? '—' : features.count}
        {features.truncated ? '+' : ''}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${layer.label}`}
        className="text-muted-foreground hover:text-destructive"
      >
        ×
      </button>
    </li>
  )
}
