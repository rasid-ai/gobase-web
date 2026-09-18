/** What the Assets page promises: specs/assets.md. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockFetch, renderApp, resetSession } from '@/test/harness'

const FIRST_PAGE = 'GET /api/catalog/assets?sort=-ingested_at&limit=12&offset=0'

function session() {
  return {
    'POST /api/auth/refresh': { status: 200, body: { access: 'access-token' } },
    'GET /api/auth/me': { status: 200, body: { username: 'viewer1', role: 'viewer' } },
  }
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    asset_id: 'cd8173bb-65ef-4bab-8bec-2be34d7157b9',
    name: 'gis_osm_boundaries_07_1',
    data_type: 'vector',
    format: 'geoparquet',
    topic_path: 'shapefiles_dresden',
    bytes: 238368,
    bbox: [13.5389, 50.9581, 14.0149, 51.198],
    summary: null,
    time_start: null,
    time_end: null,
    ingested_at: '2026-09-09T11:02:41Z',
    ...overrides,
  }
}

function page(overrides: Record<string, unknown> = {}) {
  return {
    count: 1,
    results: [item()],
    data_type_counts: [{ data_type: 'vector', count: 22 }],
    ...overrides,
  }
}

const PAGE_SIZE = 12

function items(count: number, from = 0) {
  return Array.from({ length: count }, (_, index) =>
    item({
      asset_id: `00000000-0000-0000-0000-${String(from + index).padStart(12, '0')}`,
      name: `asset_${from + index}`,
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  resetSession()
})

it('lists what the catalog holds', async () => {
  mockFetch({ ...session(), [FIRST_PAGE]: { status: 200, body: page() } })
  renderApp('/assets')

  expect(await screen.findByText('gis_osm_boundaries_07_1')).toBeInTheDocument()
  expect(screen.getByText('shapefiles_dresden')).toBeInTheDocument()
  expect(screen.getByText('233 KB')).toBeInTheDocument()
  expect(screen.getByText('2026.09.09')).toBeInTheDocument()
})

it('offers the data types the catalog reported, and no others', async () => {
  // The portal holds no list of data types — it shows back what the API sent
  // (context/integrations/kb.md).
  mockFetch({
    ...session(),
    [FIRST_PAGE]: {
      status: 200,
      body: page({
        data_type_counts: [
          { data_type: 'vector', count: 22 },
          { data_type: 'something-new', count: 3 },
        ],
      }),
    },
  })
  renderApp('/assets')

  const group = await screen.findByRole('group', { name: 'Filter by data type' })
  const options = within(group).getAllByRole('checkbox')
  expect(options.map((option) => option.textContent)).toEqual(['vector22', 'something-new3'])
})

it('asks the server again when a data type is chosen', async () => {
  const filtered = 'GET /api/catalog/assets?data_type=vector&sort=-ingested_at&limit=12&offset=0'
  const { calls } = mockFetch({
    ...session(),
    [FIRST_PAGE]: { status: 200, body: page() },
    [filtered]: { status: 200, body: page({ count: 0, results: [] }) },
  })
  const user = userEvent.setup()
  renderApp('/assets')

  await user.click(await screen.findByRole('checkbox', { name: /vector/ }))

  await waitFor(() => expect(calls).toContain(filtered))
})

it('says a filter matched nothing, rather than that there is nothing', async () => {
  const filtered = 'GET /api/catalog/assets?q=zzz&sort=-ingested_at&limit=12&offset=0'
  mockFetch({
    ...session(),
    [FIRST_PAGE]: { status: 200, body: page() },
    [filtered]: { status: 200, body: page({ count: 0, results: [] }) },
  })
  const user = userEvent.setup()
  renderApp('/assets')

  await user.type(await screen.findByLabelText('Search asset names'), 'zzz')

  expect(await screen.findByText('No assets match these filters')).toBeInTheDocument()
})

it('says the catalog is empty when nothing is filtered', async () => {
  mockFetch({
    ...session(),
    [FIRST_PAGE]: {
      status: 200,
      body: page({ count: 0, results: [], data_type_counts: [] }),
    },
  })
  renderApp('/assets')

  expect(await screen.findByText('The catalog is empty')).toBeInTheDocument()
})

it('offers to try again when the catalog cannot be read', async () => {
  mockFetch({ ...session(), [FIRST_PAGE]: { status: 500, body: {} } })
  renderApp('/assets')

  expect(await screen.findByText('The catalog could not be loaded.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
})

it('shows one page at a time and steps between them', async () => {
  const second = 'GET /api/catalog/assets?sort=-ingested_at&limit=12&offset=12'
  mockFetch({
    ...session(),
    [FIRST_PAGE]: { status: 200, body: page({ count: 20, results: items(PAGE_SIZE) }) },
    [second]: { status: 200, body: page({ count: 20, results: items(8, PAGE_SIZE) }) },
  })
  const user = userEvent.setup()
  renderApp('/assets')

  expect(await screen.findByText('1–12 of 20 assets')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Page 2' }))

  // A page replaces the one before it, rather than being appended to it.
  expect(await screen.findByText('asset_12')).toBeInTheDocument()
  expect(screen.queryByText('asset_0')).not.toBeInTheDocument()
  expect(screen.getByText('13–20 of 20 assets')).toBeInTheDocument()
})

it('offers no page control when everything fits on one page', async () => {
  mockFetch({ ...session(), [FIRST_PAGE]: { status: 200, body: page() } })
  renderApp('/assets')

  await screen.findByText('gis_osm_boundaries_07_1')
  expect(screen.queryByRole('navigation', { name: 'Pagination' })).not.toBeInTheDocument()
})

it('goes back to the first page when a filter changes', async () => {
  // Page 2 of the old list has nothing to do with page 2 of the new one, so
  // the next request has to start at offset 0.
  const second = 'GET /api/catalog/assets?sort=-ingested_at&limit=12&offset=12'
  const filtered = 'GET /api/catalog/assets?q=z&sort=-ingested_at&limit=12&offset=0'
  const { calls } = mockFetch({
    ...session(),
    [FIRST_PAGE]: { status: 200, body: page({ count: 20, results: items(PAGE_SIZE) }) },
    [second]: { status: 200, body: page({ count: 20, results: items(8, PAGE_SIZE) }) },
    [filtered]: { status: 200, body: page({ count: 1 }) },
  })
  const user = userEvent.setup()
  renderApp('/assets')

  await user.click(await screen.findByRole('button', { name: 'Page 2' }))
  await screen.findByText('asset_12')

  await user.type(screen.getByLabelText('Search asset names'), 'z')

  await waitFor(() => expect(calls).toContain(filtered))
  expect(await screen.findByText('gis_osm_boundaries_07_1')).toBeInTheDocument()
})

it('links an asset to its place on the map', async () => {
  mockFetch({ ...session(), [FIRST_PAGE]: { status: 200, body: page() } })
  renderApp('/assets')

  const link = await screen.findByRole('link', { name: 'Locate on map' })
  expect(link).toHaveAttribute('href', '/map?asset=cd8173bb-65ef-4bab-8bec-2be34d7157b9')
})

it('offers no map link for an asset with no coverage', async () => {
  // A document need not cover anywhere, and a link to nowhere is worse than
  // no link.
  mockFetch({
    ...session(),
    [FIRST_PAGE]: { status: 200, body: page({ results: [item({ bbox: null })] }) },
  })
  renderApp('/assets')

  await screen.findByText('gis_osm_boundaries_07_1')
  expect(screen.queryByRole('link', { name: 'Locate on map' })).not.toBeInTheDocument()
})

describe('filtering by area', () => {
  const BEIRUT = {
    name: 'Beirut, Lebanon',
    lat: 33.8938,
    lon: 35.5018,
    bbox: [35.4, 33.8, 35.6, 34.1],
  }
  const LINK = '/assets?place=Beirut%2C+Lebanon&bbox=35.4,33.8,35.6,34.1'
  // The generated client builds the query with URLSearchParams, which escapes
  // the commas, and in the order the params object is written.
  const AREA = 'bbox=35.4%2C33.8%2C35.6%2C34.1'
  const IN_AREA = `GET /api/catalog/assets?${AREA}&sort=-ingested_at&limit=12&offset=0`

  it('filters to the area in the link, and names it', async () => {
    mockFetch({ ...session(), [IN_AREA]: { status: 200, body: page() } })
    renderApp(LINK)

    expect(await screen.findByText('gis_osm_boundaries_07_1')).toBeInTheDocument()
    expect(screen.getByText('Beirut, Lebanon')).toBeInTheDocument()
  })

  it('keeps the name filter when a place is picked', async () => {
    // The two combine: an area plus a name is a question you can ask.
    const named = 'GET /api/catalog/assets?q=osm&sort=-ingested_at&limit=12&offset=0'
    const both = `GET /api/catalog/assets?q=osm&${AREA}&sort=-ingested_at&limit=12&offset=0`
    const { calls } = mockFetch({
      ...session(),
      [FIRST_PAGE]: { status: 200, body: page() },
      [named]: { status: 200, body: page() },
      'GET /api/places/search?q=osm': { status: 200, body: { results: [BEIRUT] } },
      [both]: { status: 200, body: page() },
    })
    const user = userEvent.setup()
    renderApp('/assets')

    await user.type(await screen.findByLabelText('Search asset names'), 'osm')
    await user.click(await screen.findByRole('option', { name: /Beirut, Lebanon/ }))

    await waitFor(() => expect(calls).toContain(both))
  })

  it('drops both parameters when the area is removed', async () => {
    const { calls } = mockFetch({
      ...session(),
      [IN_AREA]: { status: 200, body: page() },
      [FIRST_PAGE]: { status: 200, body: page() },
    })
    const user = userEvent.setup()
    renderApp(LINK)

    await user.click(await screen.findByRole('button', { name: 'Remove area Beirut, Lebanon' }))

    await waitFor(() => expect(calls).toContain(FIRST_PAGE))
    expect(screen.queryByText('Beirut, Lebanon')).toBeNull()
  })

  it('says so and shows everything when the area in the link cannot be read', async () => {
    const { calls } = mockFetch({ ...session(), [FIRST_PAGE]: { status: 200, body: page() } })
    renderApp('/assets?bbox=nonsense')

    expect(await screen.findByText(/area could not be read/)).toBeInTheDocument()
    await waitFor(() => expect(calls).toContain(FIRST_PAGE))
  })

  it('counts the area as something to clear', async () => {
    mockFetch({ ...session(), [IN_AREA]: { status: 200, body: page({ count: 0, results: [] }) } })
    renderApp(LINK)

    // Not "the catalog is empty" — the catalog is fine, this corner of it is.
    expect(await screen.findByText('No assets match these filters')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear all filters' })).toBeInTheDocument()
  })
})
