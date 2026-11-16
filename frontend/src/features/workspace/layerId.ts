import type { LayerScope } from './layers'

/**
 * A layer's id in the layer store and on the map.
 *
 * A layer drawn from the catalog is the asset itself, so its id is the asset's
 * id, and drawing it again replaces it. An Ask answer's layer is the asset in
 * one place with one filter. An answer may carry several of one asset ("2
 * schools and 7 hospitals" from one points-of-interest file), and each is its
 * own layer, so its id adds a short hash of its place and filter. A hash rather
 * than the WKT itself, because the id also names the map's source and layers.
 */
export function layerId(assetId: string, scope?: LayerScope): string {
  if (!scope) return assetId
  const filter = scope.filter
  const key = JSON.stringify([
    scope.area ?? null,
    scope.bbox ?? null,
    filter ? [filter.column, filter.op, filter.value] : null,
  ])
  return `${assetId}~${fnv1a(key)}`
}

/** FNV-1a, 32 bits, as 8 hex digits: short and stable, not for security. */
function fnv1a(text: string): string {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash.toString(16).padStart(8, '0')
}
