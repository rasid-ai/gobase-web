import { describe, expect, it } from 'vitest'

import { getMapAssetDataUrl } from '@/api/generated/map/map'

import { PAGE_SIZE, scopeParams } from './useAssetFeatures'

const AREA = 'POLYGON((35.8 34.4, 35.87 34.4, 35.87 34.46, 35.8 34.46, 35.8 34.4))'

describe('an Ask layer is read for its own place and filter', () => {
  it('sends the area and the filter as /data takes them', () => {
    const params = scopeParams({
      area: AREA,
      filter: { column: 'amenity', op: 'equals', value: 'school' },
    })
    expect(params).toEqual({
      area: AREA,
      filter_column: 'amenity',
      filter_op: 'equals',
      filter_value: ['school'],
    })
  })

  it('repeats filter_value for `in`, and turns numbers into text', () => {
    const url = getMapAssetDataUrl('a', {
      limit: PAGE_SIZE,
      ...scopeParams({ area: AREA, filter: { column: 'levels', op: 'in', value: [2, 3] } }),
    })
    const query = new URL(url, 'http://x').searchParams
    expect(query.getAll('filter_value')).toEqual(['2', '3'])
    expect(query.get('area')).toBe(AREA)
    expect(query.get('bbox')).toBeNull()
  })

  it('uses a box when the answer had no area, and nothing when it had neither', () => {
    expect(scopeParams({ bbox: [35.8, 34.4, 35.87, 34.46] })).toEqual({
      bbox: '35.8,34.4,35.87,34.46',
    })
    expect(scopeParams({})).toEqual({})
  })
})
