import type { ChatReference } from '@/api/generated/model'
import type { Bbox } from '@/features/places/bbox'
import { layerId } from '@/features/workspace/layerId'
import type { LayerScope } from '@/features/workspace/layers'

/**
 * An answer's references, sorted for the three places the panel shows them.
 *
 * The agent sends one flat list (backend/openapi.yaml, `ChatReference`): one
 * reference for every item a tool returned, cited or not. The answer cites
 * inline with markers, `[A1]`, where `A1` is the reference's `handle`
 * (gobase-agent docs/adr/006). The panel shows only what the answer cited:
 *
 * - **marks** — each marker's handle, numbered 1, 2, 3 by first appearance
 *   in this answer. The text shows the number in place of the marker.
 * - **citations** — every cited asset, with the page for a passage, in
 *   marker order. One chip per asset and page; an asset cited at a page gets
 *   no second chip without one.
 * - **assets** — the cited assets the answer hands over to open: `asset` and
 *   `raster` references.
 * - **layers** — features to put on the map: `layer` references, one per
 *   asset (a later one replaces an earlier one).
 *
 * plus **frame**, the last `frame` reference, which moves the map.
 *
 * A reference is cited when its handle appears as a marker in the text, or
 * when the agent says so (`cited: true`, sent at `done` and in stored turns).
 * The two agree: the agent sets `cited` from the markers it let through. A
 * reference with neither a handle nor `cited` is shown, as before handles.
 *
 * Display grouping only: nothing here reads the data behind a reference.
 */

/** A marker in the text, `[A1]`: one handle per pair. */
const MARKER = /\[([AP][1-9][0-9]{0,4})\]/g

export type Mark = {
  number: number
  assetId: string
  name: string | null
  /** For a passage: the page it is on, from 1. Opens a document's PDF there. */
  page: number | null
  dataType: string | null
}

export type Citation = {
  assetId: string
  page: number | null
  number: number | null
  name: string | null
  dataType: string | null
}

export type GroupedReferences = {
  marks: Map<string, Mark>
  citations: Citation[]
  layers: ChatReference[]
  frame: [number, number, number, number] | null
}

/** The markers in the text that have a reference in this turn, by handle, numbered as they first appear. */
export function citationMarks(
  text: string,
  references: readonly ChatReference[],
): Map<string, Mark> {
  const byHandle = new Map<string, ChatReference>()
  for (const reference of references) {
    if (reference.handle && reference.asset_id && !byHandle.has(reference.handle)) {
      byHandle.set(reference.handle, reference)
    }
  }

  const marks = new Map<string, Mark>()
  for (const match of text.matchAll(MARKER)) {
    const handle = match[1]
    const reference = byHandle.get(handle)
    if (!reference || marks.has(handle)) continue
    marks.set(handle, {
      number: marks.size + 1,
      assetId: reference.asset_id!,
      name: reference.name ?? null,
      page: reference.kind === 'passage' ? (reference.page ?? null) : null,
      dataType: reference.data_type ?? null,
    })
  }
  return marks
}

function isCited(reference: ChatReference, marks: Map<string, Mark>): boolean {
  if (reference.cited === true) return true
  if (reference.handle) return marks.has(reference.handle)
  return reference.cited !== false
}

export function groupReferences(
  references: readonly ChatReference[],
  text = '',
): GroupedReferences {
  const marks = citationMarks(text, references)
  const citations: Citation[] = []
  const seen = new Set<string>()
  const layers = new Map<string, ChatReference>()
  let frame: GroupedReferences['frame'] = null

  for (const reference of references) {
    if (reference.kind === 'frame') {
      if (reference.bbox?.length === 4) frame = reference.bbox as GroupedReferences['frame']
      continue
    }
    const assetId = reference.asset_id
    if (!assetId || !isCited(reference, marks)) continue

    const number = reference.handle ? (marks.get(reference.handle)?.number ?? null) : null
    const name = reference.name ?? null
    const dataType = reference.data_type ?? null

    const page = reference.kind === 'passage' ? (reference.page ?? null) : null
    const key = `${assetId}:${page ?? ''}`
    if (!seen.has(key)) {
      seen.add(key)
      citations.push({ assetId, page, number, name, dataType })
    }

    // One per distinct place and filter: an answer may count several of one asset.
    if (reference.kind === 'layer') layers.set(layerId(assetId, layerScopeOf(reference)), reference)
  }

  // A document cited at p. 14 and also handed over as an asset is one source,
  // not two: the chip with the page says more, so the bare one goes.
  const paged = new Set(citations.filter((c) => c.page !== null).map((c) => c.assetId))
  const sources = citations.filter((c) => c.page !== null || !paged.has(c.assetId))

  // Numbered chips first, in the text's order; the rest keep their arrival order.
  const rank = (citation: Citation) => citation.number ?? Number.MAX_SAFE_INTEGER
  sources.sort((a, b) => rank(a) - rank(b))

  return { marks, citations: sources, layers: [...layers.values()], frame }
}

/** What a layer was read for, in the chip's words. */
export function layerScope(reference: ChatReference): string {
  // The layer is drawn for the answer's own place (layerScopeOf), not for
  // whatever the map shows, so the label names that place.
  return reference.area || reference.bbox?.length === 4 ? "answer's area" : 'whole asset'
}

/** A layer's label: the asset, where it was read, and its filter if any. */
export function layerLabel(name: string, reference: ChatReference): string {
  const filter = reference.filter
  if (!filter) return `${name} · ${layerScope(reference)}`
  const values = Array.isArray(filter.value) ? filter.value : [filter.value]
  return `${name} · ${layerScope(reference)} · ${filter.column} ${filter.op} ${values.join(', ')}`
}

/**
 * The place and filter a `layer` reference was counted for, so the map draws
 * exactly what the answer's `total` counted (docs/adr/028).
 */
export function layerScopeOf(reference: ChatReference): LayerScope {
  return {
    ...(reference.area ? { area: reference.area } : {}),
    ...(!reference.area && reference.bbox?.length === 4 ? { bbox: reference.bbox as Bbox } : {}),
    ...(reference.filter ? { filter: reference.filter } : {}),
  }
}
