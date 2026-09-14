/** Drawing a vector asset on the map: specs/map.md and docs/adr/008. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockFetch, renderApp, resetSession } from '@/test/harness'

/**
 * MapLibre needs WebGL, which jsdom does not have.
 *
 * The map is replaced with plain elements that record what it was asked to
 * draw, so the assertions are about layers and sources rather than pixels.
 */
vi.mock('react-map-gl/maplibre', () => ({
  default: ({
    children,
    onClick,
  }: {
    children?: React.ReactNode
    onClick?: (event: { lngLat: { lng: number; lat: number } }) => void
  }) => (
    <div data-map>
      {/* Stands in for clicking the map in point mode. */}
      <button type="button" onClick={() => onClick?.({ lngLat: { lng: 13.73, lat: 51.05 } })}>
        map surface
      </button>
      {children}
    </div>
  ),
  Source: ({ id, children }: { id: string; children?: React.ReactNode }) => (
    <div data-source={id}>{children}</div>
  ),
  Layer: ({
    id,
    layout,
    filter,
  }: {
    id: string
    layout?: { visibility?: string }
    filter?: unknown
  }) => (
    <div
      data-layer={id}
      data-visibility={layout?.visibility ?? 'visible'}
      data-filter={JSON.stringify(filter ?? null)}
    />
  ),
  Marker: () => <div data-marker />,
}))

const ASSET_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
const OTHER_ID = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'

const POINT_URL = 'GET /api/map/assets?lon=13.73&lat=51.05'
const DATA_URL = `GET /api/map/assets/${ASSET_ID}/data`
const OTHER_DATA_URL = `GET /api/map/assets/${OTHER_ID}/data`

function session() {
  return {
    'POST /api/auth/refresh': { status: 200, body: { access: 'access-token' } },
    'GET /api/auth/me': { status: 200, body: { username: 'viewer1', role: 'viewer' } },
  }
}

function asset(id: string, name: string) {
  return {
    asset_id: id,
    source_uri: `s3://geobase-silver/vector/${name}.parquet`,
    format: 'parquet',
    // The catalog has no display name; a summary is what the panel shows when
    // one exists, so the fixtures carry one to keep the labels readable.
    summary: name,
    time_start: null,
    time_end: null,
  }
}

function groups() {
  return {
    groups: [
      {
        data_type: 'vector',
        assets: [asset(ASSET_ID, 'roads'), asset(OTHER_ID, 'rivers')],
      },
    ],
  }
}

function feature(type: string, coordinates: unknown) {
  return { type: 'Feature', geometry: { type, coordinates }, properties: { name: 'x' } }
}

function data(overrides: Record<string, unknown> = {}) {
  return {
    asset_id: ASSET_ID,
    count: 3,
    truncated: false,
    features: [
      feature('Point', [13.73, 51.05]),
      feature('LineString', [
        [13.7, 51.0],
        [13.8, 51.1],
      ]),
      feature('Polygon', [
        [
          [13.7, 51.0],
          [13.8, 51.0],
          [13.8, 51.1],
          [13.7, 51.0],
        ],
      ]),
    ],
    ...overrides,
  }
}

/** Click the map so the point query runs and the asset list appears. */
async function clickMap(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'map surface' }))
  await screen.findByRole('button', { name: /^Draw roads$/ })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  resetSession()
})

describe('drawing a vector asset', () => {
  it('draws its features as fill, line and circle layers', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    await waitFor(() => {
      expect(document.querySelector(`[data-source="asset-${ASSET_ID}"]`)).toBeTruthy()
    })
    // Three marks, because one file may hold points, lines and polygons at once.
    expect(document.querySelector(`[data-layer="asset-${ASSET_ID}-fill"]`)).toBeTruthy()
    expect(document.querySelector(`[data-layer="asset-${ASSET_ID}-line"]`)).toBeTruthy()
    expect(document.querySelector(`[data-layer="asset-${ASSET_ID}-circle"]`)).toBeTruthy()
  })

  it('draws Multi geometries too, not only their single-part forms', async () => {
    // `geometry-type` reports the feature's own type, so a `==` test against
    // "Polygon" silently drops every MultiPolygon. The catalog has both.
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    const filterOf = async (mark: string) => {
      const node = await waitFor(() => {
        const found = document.querySelector(`[data-layer="asset-${ASSET_ID}-${mark}"]`)
        expect(found).toBeTruthy()
        return found!
      })
      return node.getAttribute('data-filter') ?? ''
    }

    expect(await filterOf('fill')).toContain('MultiPolygon')
    expect(await filterOf('line')).toContain('MultiLineString')
    expect(await filterOf('circle')).toContain('MultiPoint')
  })

  it('lists the layer in the panel and marks the row as drawn', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    const panel = await screen.findByRole('region', { name: 'Active layers' })
    expect(within(panel).getByText('roads')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^Redraw roads$/ })).toBeInTheDocument()
  })

  it('says so when the file held more features than were returned', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data({ count: 5000, truncated: true }) },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    expect(await screen.findByText('Showing first 5000 features')).toBeInTheDocument()
  })
})

describe('managing drawn layers', () => {
  it('hides and shows a layer without fetching again', async () => {
    const { calls } = mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))
    await screen.findByRole('region', { name: 'Active layers' })
    const fetchesAfterDraw = calls.filter((call) => call === DATA_URL).length

    await user.click(screen.getByRole('checkbox', { name: 'Show roads' }))

    await waitFor(() => {
      const layer = document.querySelector(`[data-layer="asset-${ASSET_ID}-fill"]`)
      expect(layer?.getAttribute('data-visibility')).toBe('none')
    })
    // Visibility is a paint concern, not a data one.
    expect(calls.filter((call) => call === DATA_URL).length).toBe(fetchesAfterDraw)
  })

  it('removes one layer and clears them all', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
      [OTHER_DATA_URL]: { status: 200, body: { ...data(), asset_id: OTHER_ID } },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))
    await user.click(await screen.findByRole('button', { name: /^Draw rivers$/ }))
    await screen.findByText('Layers · 2')

    await user.click(screen.getByRole('button', { name: 'Remove roads' }))
    await screen.findByText('Layers · 1')
    expect(document.querySelector(`[data-source="asset-${ASSET_ID}"]`)).toBeFalsy()

    await user.click(screen.getByRole('button', { name: 'Clear all' }))

    await waitFor(() => {
      expect(screen.queryByRole('region', { name: 'Active layers' })).not.toBeInTheDocument()
    })
    expect(document.querySelector(`[data-source="asset-${OTHER_ID}"]`)).toBeFalsy()
  })

  it('keeps layers when the selection is cleared', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
      [`GET /api/map/assets/${ASSET_ID}`]: {
        status: 200,
        body: { asset_id: ASSET_ID, data_type: 'vector', metadata: {}, footprint: null },
      },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))
    await screen.findByRole('region', { name: 'Active layers' })

    // Select the asset, then clear it. The layer is not part of the selection
    // and must survive both (docs/adr/008).
    await user.click(screen.getByRole('button', { name: 'Details for roads' }))
    await user.click(await screen.findByRole('button', { name: 'Clear' }))

    expect(screen.getByRole('region', { name: 'Active layers' })).toBeInTheDocument()
    expect(document.querySelector(`[data-source="asset-${ASSET_ID}"]`)).toBeTruthy()
  })
})

describe('when the lake fails', () => {
  it('shows the failure and leaves the row usable', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 503, body: { detail: 'The data lake is unreachable' } },
    })
    const user = userEvent.setup()
    renderApp('/')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    expect(await screen.findByRole('status')).toHaveTextContent(/could not be read|unreachable/i)
    // No layer was added, so the row still offers to draw.
    expect(screen.getByRole('button', { name: /^Draw roads$/ })).toBeEnabled()
    expect(screen.queryByRole('region', { name: 'Active layers' })).not.toBeInTheDocument()
  })
})
