/** How a catalog row's values are written in the interface. */

/**
 * A byte count at human scale.
 *
 * One decimal below ten so 1.4 GB does not round to 1 GB, none above it where
 * the extra digit says nothing.
 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—'

  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }

  const rounded = unit > 0 && value < 10 ? value.toFixed(1) : Math.round(value)
  return `${rounded} ${units[unit]}`
}

/**
 * An ingestion date as data chrome: dotted, fixed width, mono.
 *
 * Dotted rather than localised on purpose — it sits in a mono column alongside
 * ids and coordinates, where a date that changes width between locales would
 * break the alignment (context/design-system.md).
 */
export function formatIngested(iso: string | null | undefined): string {
  if (!iso) return '—'
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return '—'

  const pad = (part: number) => String(part).padStart(2, '0')
  return `${when.getFullYear()}.${pad(when.getMonth() + 1)}.${pad(when.getDate())}`
}

/** A coverage box as a coordinate pair, latitude first, as the map writes them. */
export function formatBbox(bbox: readonly number[] | null | undefined): string | null {
  if (!bbox || bbox.length !== 4) return null
  const [minLon, minLat, maxLon, maxLat] = bbox
  const round = (value: number) => value.toFixed(4)
  return `${round(minLat)},${round(minLon)} → ${round(maxLat)},${round(maxLon)}`
}
