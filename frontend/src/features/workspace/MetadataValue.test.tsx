/** How a metadata value is shown: docs/adr/016, specs/map.md. */

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MetadataValue, formatScalar, isStructured } from './MetadataValue'

describe('which values are tables', () => {
  it.each([
    [{ year: '2019' }, true],
    [[{ name: 'highway' }], true],
    [[1, { a: 1 }], true],
    [[2, 4, 8], false],
    ['{"1": "water"}', false],
    [42, false],
    [null, false],
  ])('%j → %s', (value, structured) => {
    expect(isStructured(value)).toBe(structured)
  })
})

describe('plain values', () => {
  it('prints a list of plain values on one line', () => {
    expect(formatScalar([2, 4, 8])).toBe('2, 4, 8')
  })

  it('shows a dash for nothing', () => {
    expect(formatScalar(null)).toBe('—')
    expect(formatScalar('')).toBe('—')
    expect(formatScalar([])).toBe('—')
  })

  it('leaves JSON stored as text as text, rather than guessing', () => {
    expect(formatScalar('{"1": "water"}')).toBe('{"1": "water"}')
  })
})

describe('tables', () => {
  it('turns a list of objects into one column per key, in first-seen order', () => {
    render(
      <MetadataValue
        value={[
          { name: 'highway', dtype: 'string' },
          { name: 'maxspeed', dtype: 'int', note: 'km/h' },
        ]}
      />,
    )

    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    expect(headers).toEqual(['name', 'dtype', 'note'])
    // A key a row lacks is an empty cell, not a shifted row.
    const [, first] = screen.getAllByRole('row')
    expect(
      within(first)
        .getAllByRole('cell')
        .map((cell) => cell.textContent),
    ).toEqual(['highway', 'string', '—'])
  })

  it('turns an object into key and value rows, nesting as deep as it goes', () => {
    render(<MetadataValue value={{ default: { year: '2019', source: 'STAC' } }} />)

    const tables = screen.getAllByRole('table')
    expect(tables).toHaveLength(2)
    expect(within(tables[0]).getByRole('rowheader', { name: 'default' })).toBeInTheDocument()
    expect(within(tables[1]).getByRole('rowheader', { name: 'year' })).toBeInTheDocument()
    expect(within(tables[1]).getByText('2019')).toBeInTheDocument()
  })

  it('never prints raw JSON', () => {
    const { container } = render(<MetadataValue value={[{ stats: { min: 1, max: 11 } }]} />)
    expect(container.textContent).not.toContain('{')
  })
})
