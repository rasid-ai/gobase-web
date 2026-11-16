/** Reading an area out of a link: docs/adr/011. */

import { describe, expect, it } from 'vitest'

import { parseBbox, serializeBbox, type Bbox } from './bbox'

const BEIRUT: Bbox = [35.4, 33.8, 35.6, 34.1]

describe('parseBbox', () => {
  it('reads four numbers as min_lon, min_lat, max_lon, max_lat', () => {
    expect(parseBbox('35.4,33.8,35.6,34.1')).toEqual(BEIRUT)
  })

  it('accepts a zero-area box, which asks what covers one spot', () => {
    expect(parseBbox('35.5,33.9,35.5,33.9')).toEqual([35.5, 33.9, 35.5, 33.9])
  })

  it('accepts negatives and a leading plus', () => {
    expect(parseBbox('-13.5,-51.2,+14.1,-50.9')).toEqual([-13.5, -51.2, 14.1, -50.9])
  })

  it.each([
    ['nothing at all', ''],
    ['nothing at all', null],
    ['three numbers', '35.4,33.8,35.6'],
    ['five numbers', '35.4,33.8,35.6,34.1,1'],
    ['words', 'a,b,c,d'],
    // Number() takes all three of these, which is why there is a pattern.
    ['hexadecimal', '0x10,33.8,35.6,34.1'],
    ['exponents', '1e2,33.8,35.6,34.1'],
    ['infinity', 'Infinity,33.8,35.6,34.1'],
    ['a longitude past 180', '200,33.8,201,34.1'],
    ['a latitude past 90', '35.4,-91,35.6,-92'],
    ['an inside-out box', '35.6,33.8,35.4,34.1'],
  ])('refuses %s', (_why, raw) => {
    expect(parseBbox(raw)).toBeNull()
  })
})

describe('serializeBbox', () => {
  it('round-trips', () => {
    expect(parseBbox(serializeBbox(BEIRUT))).toEqual(BEIRUT)
  })

  it('writes one canonical form, so 34.0 and 34 make the same link', () => {
    expect(serializeBbox(parseBbox('35.4,33.8,35.6,34.0')!)).toBe('35.4,33.8,35.6,34')
  })
})
