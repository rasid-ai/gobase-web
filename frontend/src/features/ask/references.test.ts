import { describe, expect, it } from 'vitest'

import type { ChatReference } from '@/api/generated/model'

import { groupReferences, layerScope } from './references'

const DOC = 'cccccccc-dddd-eeee-ffff-000000000000'
const ROADS = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
const LANDCOVER = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'

describe('groupReferences', () => {
  it('cites every asset an answer used, once per asset and page', () => {
    const references: ChatReference[] = [
      { kind: 'passage', asset_id: DOC, chunk_id: 'a', page: 14 },
      { kind: 'passage', asset_id: DOC, chunk_id: 'b', page: 14 },
      { kind: 'passage', asset_id: DOC, chunk_id: 'c', page: 20 },
      { kind: 'layer', asset_id: ROADS, bbox: [0, 0, 1, 1], total: 3 },
      { kind: 'asset', asset_id: ROADS },
    ]

    expect(groupReferences(references).citations).toEqual([
      { assetId: DOC, page: 14 },
      { assetId: DOC, page: 20 },
      { assetId: ROADS, page: null },
    ])
  })

  it('drops the bare citation of an asset already cited at a page', () => {
    const grouped = groupReferences([
      { kind: 'asset', asset_id: DOC },
      { kind: 'passage', asset_id: DOC, chunk_id: 'a', page: 14 },
      { kind: 'asset', asset_id: ROADS },
    ])

    expect(grouped.citations).toEqual([
      { assetId: DOC, page: 14 },
      { assetId: ROADS, page: null },
    ])
    // Still handed over to open, in the Assets box.
    expect(grouped.assets).toEqual([DOC, ROADS])
  })

  it('hands over assets and rasters as assets, and layers as layers', () => {
    const layer: ChatReference = { kind: 'layer', asset_id: ROADS, area: 'POLYGON((...))' }
    const grouped = groupReferences([
      { kind: 'asset', asset_id: DOC },
      { kind: 'raster', asset_id: LANDCOVER, stats: { built_area: 0.4 } },
      layer,
    ])

    expect(grouped.assets).toEqual([DOC, LANDCOVER])
    expect(grouped.layers).toEqual([layer])
  })

  it('keeps one layer per asset, the later one', () => {
    const later: ChatReference = { kind: 'layer', asset_id: ROADS, total: 9 }
    const grouped = groupReferences([{ kind: 'layer', asset_id: ROADS, total: 3 }, later])

    expect(grouped.layers).toEqual([later])
  })

  it('takes the last frame, and cites nothing for it', () => {
    const grouped = groupReferences([
      { kind: 'frame', bbox: [0, 0, 1, 1] },
      { kind: 'frame', bbox: [35, 33, 36, 34] },
    ])

    expect(grouped.frame).toEqual([35, 33, 36, 34])
    expect(grouped.citations).toEqual([])
  })
})

describe('layerScope', () => {
  it('names a drawn area, and otherwise the view', () => {
    expect(layerScope({ kind: 'layer', asset_id: ROADS, area: 'POLYGON((...))' })).toBe(
      'drawn area',
    )
    expect(layerScope({ kind: 'layer', asset_id: ROADS, bbox: [0, 0, 1, 1] })).toBe('this view')
  })
})
