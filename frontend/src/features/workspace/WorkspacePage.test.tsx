/** Drawing a vector asset on the map: specs/map.md and docs/adr/008. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getMapAssetDataUrl } from '@/api/generated/map/map'
import type { Bbox } from '@/features/places/bbox'
import { serializeBbox } from '@/features/places/bbox'
import { mockFetch, renderApp, resetSession } from '@/test/harness'

import { PAGE_BUDGET, PAGE_SIZE } from './useAssetFeatures'
import { windowFor } from './view'

/**
 * MapLibre needs WebGL, which jsdom does not have.
 *
 * The map is replaced with plain elements that record what it was asked to
 * draw, so the assertions are about layers and sources rather than pixels.
 */
/** Where the stub map is looking. Tests move it to make the window change. */
const HOME: Bbox = [13.5, 50.9, 14.0, 51.2]
const camera_view = { bounds: HOME, zoom: 8.5 }

/** What the page asked the camera to do, so framing can be asserted. */
const camera = {
  fitBounds: vi.fn(),
  flyTo: vi.fn(),
  getZoom: () => camera_view.zoom,
  // The page reads the window off the map, so the stub has to have one.
  getBounds: () => ({
    getWest: () => camera_view.bounds[0],
    getSouth: () => camera_view.bounds[1],
    getEast: () => camera_view.bounds[2],
    getNorth: () => camera_view.bounds[3],
  }),
}

vi.mock('react-map-gl/maplibre', async () => {
  const { useEffect } = await import('react')
  // A named component, not an inline arrow on `default`: it uses a hook, and
  // the rules-of-hooks lint reads a lowercase name as a plain function.
  function StubMap({
    children,
    onClick,
    onLoad,
    onMoveEnd,
    ref,
  }: {
    children?: React.ReactNode
    onClick?: (event: { lngLat: { lng: number; lat: number } }) => void
    onLoad?: () => void
    onMoveEnd?: () => void
    ref?: { current: unknown }
  }) {
    // react-map-gl hands back a ref the page steers the map through; the stub
    // records the calls instead of moving anything.
    if (ref) ref.current = camera
    // The real map reports its first view when it loads, and nothing is read
    // until it does.
    useEffect(() => {
      onLoad?.()
    }, [onLoad])
    return (
      <div data-map>
        {/* Stands in for clicking the map in point mode. */}
        <button type="button" onClick={() => onClick?.({ lngLat: { lng: 13.73, lat: 51.05 } })}>
          map surface
        </button>
        {/* Stands in for a pan or zoom coming to rest. */}
        <button type="button" onClick={() => onMoveEnd?.()}>
          settle map
        </button>
        {children}
      </div>
    )
  }

  return {
    default: StubMap,
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
  }
})

const ASSET_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
const OTHER_ID = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'

const POINT_URL = 'GET /api/map/assets?lon=13.73&lat=51.05'

/**
 * The features request for an asset, for the window the stub map is showing.
 *
 * Built with the client's own URL builder and the real `windowFor`, because a
 * hand-written query string would be asserting the snapping arithmetic in
 * every test. That arithmetic has its own tests in `view.test.ts`.
 */
function dataUrl(id: string, cursor?: number, bounds: Bbox = HOME, zoom = 8.5) {
  return `GET ${getMapAssetDataUrl(id, {
    limit: PAGE_SIZE,
    bbox: serializeBbox(windowFor(bounds, zoom)),
    ...(cursor === undefined ? {} : { cursor }),
  })}`
}

const DATA_URL = dataUrl(ASSET_ID)
const OTHER_DATA_URL = dataUrl(OTHER_ID)

/** Point the stub map somewhere else, then settle it. */
async function moveTo(user: ReturnType<typeof userEvent.setup>, bounds: Bbox, zoom = 8.5) {
  camera_view.bounds = bounds
  camera_view.zoom = zoom
  await user.click(screen.getByRole('button', { name: 'settle map' }))
}

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
    next_cursor: null,
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

beforeEach(() => {
  camera.fitBounds.mockClear()
  // The stub camera is module state, so a test that moved it would otherwise
  // hand the next one a different window and a URL nothing mocked.
  camera_view.bounds = HOME
  camera_view.zoom = 8.5
})

describe('drawing a vector asset', () => {
  it('draws its features as fill, line and circle layers', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/map')

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
    renderApp('/map')

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
    renderApp('/map')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    const panel = await screen.findByRole('region', { name: 'Active layers' })
    expect(within(panel).getByText('roads')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /^Redraw roads$/ })).toBeInTheDocument()
  })

  it('says so when the area holds more than the budget reads', async () => {
    // Every page offers another, so the budget is what stops it rather than
    // the data running out.
    const more = data({ next_cursor: 999 })
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: more },
      [dataUrl(ASSET_ID, 999)]: { status: 200, body: more },
    })
    const user = userEvent.setup()
    renderApp('/map')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    // Three features a page until the budget stops it. Derived rather than
    // written out, so retuning the budget does not need this edited.
    const shown = PAGE_BUDGET * 3
    expect(
      await screen.findByText(new RegExp(`${shown} features shown · zoom in for the rest`)),
    ).toBeInTheDocument()
  })

  it('reads the layer again for the new area when the map settles', async () => {
    const ELSEWHERE: Bbox = [20.0, 40.0, 20.5, 40.3]
    const { calls } = mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
      [dataUrl(ASSET_ID, undefined, ELSEWHERE)]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/map')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))
    await waitFor(() => expect(calls).toContain(DATA_URL))

    await moveTo(user, ELSEWHERE)

    await waitFor(() => expect(calls).toContain(dataUrl(ASSET_ID, undefined, ELSEWHERE)))
  })

  it('does not read again for a move that lands in the same window', async () => {
    const { calls } = mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp('/map')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))
    await waitFor(() => expect(calls).toContain(DATA_URL))
    const before = calls.filter((call) => call === DATA_URL).length

    // A nudge far smaller than a grid cell: the window is unchanged, so the
    // cache answers and nothing goes out.
    await moveTo(user, [13.51, 50.91, 14.01, 51.21])

    expect(calls.filter((call) => call === DATA_URL).length).toBe(before)
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
    renderApp('/map')

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
    renderApp('/map')

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
    renderApp('/map')

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
  it('says so on the layer, and keeps the layer', async () => {
    mockFetch({
      ...session(),
      [POINT_URL]: { status: 200, body: groups() },
      [DATA_URL]: { status: 503, body: { detail: 'The data lake is unreachable' } },
    })
    const user = userEvent.setup()
    renderApp('/map')

    await clickMap(user)
    await user.click(screen.getByRole('button', { name: /^Draw roads$/ }))

    // The failure belongs to the layer, not to the moment: the layer is read
    // again on every move, so a toast per failed pan would be noise.
    expect(await screen.findByText('Could not read this layer')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Active layers' })).toBeInTheDocument()
  })
})

describe('an asset linked from the Assets page', () => {
  const DETAIL_URL = `GET /api/map/assets/${ASSET_ID}`

  function detail() {
    return {
      asset_id: ASSET_ID,
      data_type: 'vector',
      metadata: { source_uri: 's3://geobase-silver/vector/roads.parquet' },
      footprint: {
        type: 'Polygon',
        coordinates: [
          [
            [13.5, 50.9],
            [14.0, 50.9],
            [14.0, 51.2],
            [13.5, 51.2],
            [13.5, 50.9],
          ],
        ],
      },
    }
  }

  it('opens its metadata with no point clicked', async () => {
    // The panel used to need a point click behind it; a link has none.
    mockFetch({ ...session(), [DETAIL_URL]: { status: 200, body: detail() } })
    renderApp(`/map?asset=${ASSET_ID}`)

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    expect(within(panel).getByText('source_uri')).toBeInTheDocument()
  })

  it('draws its footprint', async () => {
    mockFetch({ ...session(), [DETAIL_URL]: { status: 200, body: detail() } })
    renderApp(`/map?asset=${ASSET_ID}`)

    await waitFor(() => {
      expect(document.querySelector('[data-source="footprint"]')).toBeTruthy()
    })
  })

  it('stays cleared once cleared', async () => {
    // Clearing has to drop the parameter too, or the link re-selects the asset
    // on the very next render.
    mockFetch({ ...session(), [DETAIL_URL]: { status: 200, body: detail() } })
    const user = userEvent.setup()
    renderApp(`/map?asset=${ASSET_ID}`)

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    await user.click(within(panel).getByRole('button', { name: 'Clear' }))

    await waitFor(() => {
      expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
    })
  })

  it('draws its features from the metadata pane, with no map click', async () => {
    // The whole point of the link: an asset reached from the Assets page never
    // passes through the point list, so the pane has to be able to draw.
    mockFetch({
      ...session(),
      [DETAIL_URL]: { status: 200, body: detail() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp(`/map?asset=${ASSET_ID}`)

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    await user.click(within(panel).getByRole('button', { name: 'Draw' }))

    await waitFor(() => {
      expect(document.querySelector(`[data-source="asset-${ASSET_ID}"]`)).toBeTruthy()
    })
  })

  it('says so once an asset is already drawn', async () => {
    mockFetch({
      ...session(),
      [DETAIL_URL]: { status: 200, body: detail() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp(`/map?asset=${ASSET_ID}`)

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    await user.click(within(panel).getByRole('button', { name: 'Draw' }))

    expect(await within(panel).findByRole('button', { name: 'Redraw' })).toBeInTheDocument()
  })

  it('reports an asset that has nothing to draw, rather than failing quietly', async () => {
    mockFetch({
      ...session(),
      [DETAIL_URL]: { status: 200, body: detail() },
      [DATA_URL]: { status: 404, body: {} },
    })
    const user = userEvent.setup()
    renderApp(`/map?asset=${ASSET_ID}`)

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    await user.click(within(panel).getByRole('button', { name: 'Draw' }))

    expect(await screen.findByText('No vector data to draw')).toBeInTheDocument()
  })

  it('drops the coverage box once the data itself is on the map', async () => {
    // The box stands in for data you cannot see. Leaving it up once you can
    // outlines the very thing it was describing.
    mockFetch({
      ...session(),
      [DETAIL_URL]: { status: 200, body: detail() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp(`/map?asset=${ASSET_ID}`)

    await waitFor(() => {
      expect(document.querySelector('[data-source="footprint"]')).toBeTruthy()
    })

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    await user.click(within(panel).getByRole('button', { name: 'Draw' }))

    await waitFor(() => {
      expect(document.querySelector(`[data-source="asset-${ASSET_ID}"]`)).toBeTruthy()
    })
    expect(document.querySelector('[data-source="footprint"]')).toBeNull()
  })

  it('brings the coverage box back when the data is hidden', async () => {
    mockFetch({
      ...session(),
      [DETAIL_URL]: { status: 200, body: detail() },
      [DATA_URL]: { status: 200, body: data() },
    })
    const user = userEvent.setup()
    renderApp(`/map?asset=${ASSET_ID}`)

    const panel = await screen.findByRole('complementary', { name: 'Selected asset' })
    await user.click(within(panel).getByRole('button', { name: 'Draw' }))
    await waitFor(() => {
      expect(document.querySelector('[data-source="footprint"]')).toBeNull()
    })

    // Hiding the layer leaves nothing to see again, so the box is useful again.
    await user.click(screen.getByRole('checkbox', { name: /roads/i }))

    await waitFor(() => {
      expect(document.querySelector('[data-source="footprint"]')).toBeTruthy()
    })
  })

  it('frames the view on the asset it was sent to', async () => {
    mockFetch({ ...session(), [DETAIL_URL]: { status: 200, body: detail() } })
    renderApp(`/map?asset=${ASSET_ID}`)

    await screen.findByRole('complementary', { name: 'Selected asset' })
    await waitFor(() => expect(camera.fitBounds).toHaveBeenCalled())

    const [box] = camera.fitBounds.mock.calls[0]
    expect(box).toEqual([
      [13.5, 50.9],
      [14.0, 51.2],
    ])
  })

  it('does not zoom past the basemap for an asset that covers a single point', async () => {
    // A coverage with no area is real data — and fitBounds answers it with
    // maximum zoom, far past the deepest tile there is, leaving a blank
    // screen that reads as a broken map.
    const pointFootprint = {
      ...detail(),
      footprint: {
        type: 'Polygon',
        coordinates: [
          [
            [35.7, 33.9],
            [35.7, 33.9],
            [35.7, 33.9],
            [35.7, 33.9],
            [35.7, 33.9],
          ],
        ],
      },
    }
    mockFetch({ ...session(), [DETAIL_URL]: { status: 200, body: pointFootprint } })
    renderApp(`/map?asset=${ASSET_ID}`)

    await screen.findByRole('complementary', { name: 'Selected asset' })
    await waitFor(() => expect(camera.fitBounds).toHaveBeenCalled())

    const [box, options] = camera.fitBounds.mock.calls[0]
    expect(box).toEqual([
      [35.7, 33.9],
      [35.7, 33.9],
    ])
    expect(options.maxZoom).toBeLessThanOrEqual(16)
  })

  it('asks the catalog once, not once per render', async () => {
    const { calls } = mockFetch({
      ...session(),
      [DETAIL_URL]: { status: 200, body: detail() },
    })
    renderApp(`/map?asset=${ASSET_ID}`)

    await screen.findByRole('complementary', { name: 'Selected asset' })
    expect(calls.filter((call) => call === DETAIL_URL)).toHaveLength(1)
  })
})
