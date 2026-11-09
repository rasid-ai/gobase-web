import type { ChatReference } from '@/api/generated/model'

/**
 * An answer's references, sorted for the three places the panel shows them.
 *
 * The agent sends one flat list (backend/openapi.yaml, `ChatReference`). The
 * design shows three things under an answer, and this is how the list fills
 * them:
 *
 * - **citations** — every asset the answer drew on, with the page for a
 *   passage. One chip per asset and page; an asset cited at a page gets no
 *   second chip without one.
 * - **assets** — the assets the answer hands over to open: `asset` and
 *   `raster` references.
 * - **layers** — features to put on the map: `layer` references, one per
 *   asset (a later one replaces an earlier one).
 *
 * plus **frame**, the last `frame` reference, which moves the map.
 *
 * Display grouping only: nothing here reads the data behind a reference.
 */

export type Citation = { assetId: string; page: number | null }

export type GroupedReferences = {
  citations: Citation[]
  assets: string[]
  layers: ChatReference[]
  frame: [number, number, number, number] | null
}

export function groupReferences(references: readonly ChatReference[]): GroupedReferences {
  const citations: Citation[] = []
  const cited = new Set<string>()
  const assets: string[] = []
  const layers = new Map<string, ChatReference>()
  let frame: GroupedReferences['frame'] = null

  for (const reference of references) {
    if (reference.kind === 'frame') {
      if (reference.bbox?.length === 4) frame = reference.bbox as GroupedReferences['frame']
      continue
    }
    const assetId = reference.asset_id
    if (!assetId) continue

    const page = reference.kind === 'passage' ? (reference.page ?? null) : null
    const key = `${assetId}:${page ?? ''}`
    if (!cited.has(key)) {
      cited.add(key)
      citations.push({ assetId, page })
    }

    if ((reference.kind === 'asset' || reference.kind === 'raster') && !assets.includes(assetId)) {
      assets.push(assetId)
    }
    if (reference.kind === 'layer') layers.set(assetId, reference)
  }

  // A document cited at p. 14 and also handed over as an asset is one source,
  // not two: the chip with the page says more, so the bare one goes.
  const paged = new Set(citations.filter((c) => c.page !== null).map((c) => c.assetId))
  const sources = citations.filter((c) => c.page !== null || !paged.has(c.assetId))

  return { citations: sources, assets, layers: [...layers.values()], frame }
}

/** What a layer was read for, in the chip's words. */
export function layerScope(reference: ChatReference): string {
  return reference.area ? 'drawn area' : 'this view'
}
