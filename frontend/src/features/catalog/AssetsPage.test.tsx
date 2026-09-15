/** What the Assets page promises: specs/assets.md. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'

import { mockFetch, renderApp, resetSession } from '@/test/harness'

const FIRST_PAGE = 'GET /api/catalog/assets?sort=-ingested_at&limit=24&offset=0'

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
  const filtered = 'GET /api/catalog/assets?data_type=vector&sort=-ingested_at&limit=24&offset=0'
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
  const filtered = 'GET /api/catalog/assets?q=zzz&sort=-ingested_at&limit=24&offset=0'
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

it('keeps the pages it has when asked for more', async () => {
  const second = 'GET /api/catalog/assets?sort=-ingested_at&limit=24&offset=1'
  mockFetch({
    ...session(),
    [FIRST_PAGE]: { status: 200, body: page({ count: 2 }) },
    [second]: {
      status: 200,
      body: page({
        count: 2,
        results: [item({ asset_id: 'aaaaaaaa-0000-0000-0000-000000000000', name: 'second' })],
      }),
    },
  })
  const user = userEvent.setup()
  renderApp('/assets')

  await user.click(await screen.findByRole('button', { name: 'Load more' }))

  expect(await screen.findByText('second')).toBeInTheDocument()
  expect(screen.getByText('gis_osm_boundaries_07_1')).toBeInTheDocument()
  expect(screen.getByText('2 assets')).toBeInTheDocument()
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
