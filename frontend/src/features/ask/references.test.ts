import { describe, expect, it } from 'vitest'

import type { ChatReference } from '@/api/generated/model'

import { layerId } from '@/features/workspace/layerId'

import { citationMarks, groupReferences, layerLabel, layerScope, layerScopeOf } from './references'

const DOC = 'cccccccc-dddd-eeee-ffff-000000000000'
const ROADS = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
const LANDCOVER = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'

/** A citation as the panel shows it, with nothing known beyond its id. */
const bare = (assetId: string, page: number | null = null) => ({
  assetId,
  page,
  number: null,
  name: null,
  dataType: null,
})

describe('citationMarks', () => {
  const references: ChatReference[] = [
    { kind: 'asset', handle: 'A1', asset_id: ROADS, name: 'roads', data_type: 'vector' },
    { kind: 'asset', handle: 'A2', asset_id: LANDCOVER, name: 'landcover', data_type: 'raster' },
    { kind: 'asset', handle: 'A3', asset_id: DOC, name: 'Airport report', data_type: 'document' },
  ]

  it('numbers the handles the text cites, in order of first appearance', () => {
    const marks = citationMarks('Roads [A3] cross the area [A1][A3], see [A1].', references)

    expect([...marks.entries()]).toEqual([
      ['A3', { number: 1, assetId: DOC, name: 'Airport report', page: null, dataType: 'document' }],
      ['A1', { number: 2, assetId: ROADS, name: 'roads', page: null, dataType: 'vector' }],
    ])
  })

  it('ignores a bracket with no reference behind it', () => {
    const marks = citationMarks('Quoted [sic] from [A9], and [A1, A2] as one pair.', references)

    expect(marks.size).toBe(0)
  })
})

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
      bare(DOC, 14),
      bare(DOC, 20),
      bare(ROADS),
    ])
  })

  it('drops the bare citation of an asset already cited at a page', () => {
    const grouped = groupReferences([
      { kind: 'asset', asset_id: DOC },
      { kind: 'passage', asset_id: DOC, chunk_id: 'a', page: 14 },
      { kind: 'asset', asset_id: ROADS },
    ])

    expect(grouped.citations).toEqual([bare(DOC, 14), bare(ROADS)])
  })

  it('hands over layers for the map, and cites assets and rasters only as citations', () => {
    const layer: ChatReference = { kind: 'layer', asset_id: ROADS, area: 'POLYGON((...))' }
    const grouped = groupReferences([
      { kind: 'asset', asset_id: DOC },
      { kind: 'raster', asset_id: LANDCOVER, stats: { built_area: 0.4 } },
      layer,
    ])

    expect(grouped.citations.map((c) => c.assetId)).toEqual([DOC, LANDCOVER, ROADS])
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

  describe('with handles', () => {
    const roads: ChatReference = {
      kind: 'asset',
      handle: 'A1',
      asset_id: ROADS,
      name: 'roads',
      data_type: 'vector',
    }
    const landcover: ChatReference = {
      kind: 'asset',
      handle: 'A2',
      asset_id: LANDCOVER,
      name: 'landcover',
      data_type: 'raster',
    }
    const report: ChatReference = {
      kind: 'asset',
      handle: 'A3',
      asset_id: DOC,
      name: 'Airport report',
      data_type: 'document',
    }

    it('shows only what the text cites, numbered as the text does, while streaming', () => {
      const grouped = groupReferences([roads, landcover, report], 'See [A3] and then [A1].')

      expect(grouped.citations).toEqual([
        { assetId: DOC, page: null, number: 1, name: 'Airport report', dataType: 'document' },
        { assetId: ROADS, page: null, number: 2, name: 'roads', dataType: 'vector' },
      ])
      expect(grouped.marks.get('A3')?.number).toBe(1)
    })

    it("follows the agent's word at done: cited shows, uncited does not", () => {
      const grouped = groupReferences(
        [
          { ...roads, cited: true },
          { ...landcover, cited: false },
        ],
        'Roads everywhere [A1].',
      )

      expect(grouped.citations.map((c) => c.assetId)).toEqual([ROADS])
    })

    it('still shows a cited reference whose marker the text lost', () => {
      // The agent's `cited` is checked; the text is what streamed. Trust the flag.
      const grouped = groupReferences([{ ...roads, cited: true }], 'No marker here.')

      expect(grouped.citations).toEqual([
        { assetId: ROADS, page: null, number: null, name: 'roads', dataType: 'vector' },
      ])
    })

    it('shows a reference with neither handle nor cited, as before handles', () => {
      const grouped = groupReferences([{ kind: 'asset', asset_id: DOC }, roads], 'Nothing cited.')

      expect(grouped.citations).toEqual([bare(DOC)])
    })

    it('keeps an uncited layer off the list', () => {
      const layer: ChatReference = { kind: 'layer', handle: 'A1', asset_id: ROADS, total: 3 }

      expect(groupReferences([layer], 'No roads after all.').layers).toEqual([])
      expect(groupReferences([layer], 'Roads [A1].').layers).toEqual([layer])
    })

    it('takes several layers of one asset that share its handle as one mark and one chip', () => {
      const asset: ChatReference = { kind: 'asset', handle: 'A1', asset_id: ROADS }
      const first: ChatReference = { kind: 'layer', handle: 'A1', asset_id: ROADS, total: 2 }
      const last: ChatReference = { kind: 'layer', handle: 'A1', asset_id: ROADS, total: 7 }
      const text = '2 primary roads [A1] and 7 tracks [A1].'

      const grouped = groupReferences([asset, first, last], text)

      expect(citationMarks(text, [asset, first, last]).size).toBe(1)
      expect(grouped.citations).toHaveLength(1)
      expect(grouped.layers).toEqual([last])
    })
  })
})

describe('layerScope', () => {
  it("names the answer's area, and otherwise the whole asset", () => {
    expect(layerScope({ kind: 'layer', asset_id: ROADS, area: 'POLYGON((...))' })).toBe(
      "answer's area",
    )
    expect(layerScope({ kind: 'layer', asset_id: ROADS, bbox: [0, 0, 1, 1] })).toBe("answer's area")
    expect(layerScope({ kind: 'layer', asset_id: ROADS })).toBe('whole asset')
  })
})

describe('layerScopeOf', () => {
  it('keeps the area, else the box, and the filter', () => {
    const filter = { column: 'amenity', op: 'equals' as const, value: 'school' }
    expect(
      layerScopeOf({
        kind: 'layer',
        asset_id: ROADS,
        area: 'POLYGON((...))',
        bbox: [0, 0, 1, 1],
        filter,
      }),
    ).toEqual({ area: 'POLYGON((...))', filter })
    expect(layerScopeOf({ kind: 'layer', asset_id: ROADS, bbox: [0, 0, 1, 1] })).toEqual({
      bbox: [0, 0, 1, 1],
    })
  })
})

describe('several layers of one asset', () => {
  const area = 'POLYGON((35.8 34.4, 35.87 34.4, 35.87 34.46, 35.8 34.46, 35.8 34.4))'
  const schools: ChatReference = {
    kind: 'layer',
    handle: 'A1',
    asset_id: ROADS,
    area,
    filter: { column: 'amenity', op: 'equals', value: 'school' },
    total: 2,
    cited: true,
  }
  const hospitals: ChatReference = {
    ...schools,
    filter: { column: 'amenity', op: 'in', value: ['hospital', 'clinic'] },
    total: 7,
  }

  it('keeps each place and filter as its own layer, with its own id', () => {
    const grouped = groupReferences([schools, hospitals, { ...schools }], 'See [A1].')
    expect(grouped.layers.map((layer) => layer.total)).toEqual([2, 7])
    const ids = grouped.layers.map((layer) => layerId(ROADS, layerScopeOf(layer)))
    expect(new Set(ids).size).toBe(2)
    expect(ids.every((id) => id.startsWith(`${ROADS}~`))).toBe(true)
    // A catalog layer is the asset itself.
    expect(layerId(ROADS)).toBe(ROADS)
  })

  it('names the filter in the label', () => {
    expect(layerLabel('poi', hospitals)).toBe("poi · answer's area · amenity in hospital, clinic")
    expect(layerLabel('poi', { kind: 'layer', asset_id: ROADS })).toBe('poi · whole asset')
  })
})
