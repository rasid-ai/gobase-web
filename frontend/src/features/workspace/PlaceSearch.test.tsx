/** Going to a place or a typed coordinate: specs/map.md. */

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockFetch, renderApp, resetSession } from '@/test/harness'

/**
 * The map is replaced, as in WorkspacePage.test.tsx, but this one also exposes
 * the ref: the zoom rule lives in `flyTo`'s arguments and is worth asserting.
 *
 * React 19 passes `ref` as an ordinary prop, so no `forwardRef` is needed.
 */
const mapRef = vi.hoisted(() => ({
  flyTo: vi.fn(),
  fitBounds: vi.fn(),
  getZoom: vi.fn(() => 5),
}))

vi.mock('react-map-gl/maplibre', async () => {
  const { useImperativeHandle } = await import('react')

  // Named and capitalised so the hooks lint rule sees a component.
  function MockMap({
    children,
    onClick,
    ref,
  }: {
    children?: React.ReactNode
    onClick?: (event: { lngLat: { lng: number; lat: number } }) => void
    ref?: React.Ref<unknown>
  }) {
    useImperativeHandle(ref, () => mapRef)
    return (
      <div data-map>
        <button type="button" onClick={() => onClick?.({ lngLat: { lng: 1, lat: 2 } })}>
          map surface
        </button>
        {children}
      </div>
    )
  }

  return {
    default: MockMap,
    Source: ({ id, children }: { id: string; children?: React.ReactNode }) => (
      <div data-source={id}>{children}</div>
    ),
    Layer: ({ id }: { id: string }) => <div data-layer={id} />,
    Marker: ({ longitude, latitude }: { longitude: number; latitude: number }) => (
      <div data-marker data-lon={longitude} data-lat={latitude} />
    ),
  }
})

// Dresden, as a mapping site writes it: latitude first.
const DRESDEN = '51.0504, 13.7373'
const DRESDEN_URL = 'GET /api/map/assets?lon=13.7373&lat=51.0504'
const EMPTY_URL = 'GET /api/map/assets?lon=0&lat=0'

function session() {
  return {
    'POST /api/auth/refresh': { status: 200, body: { access: 'access-token' } },
    'GET /api/auth/me': { status: 200, body: { username: 'viewer1', role: 'viewer' } },
  }
}

function groups() {
  return {
    groups: [
      {
        data_type: 'vector',
        assets: [
          {
            asset_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            source_uri: 's3://geobase-silver/vector/roads.parquet',
            format: 'parquet',
            summary: 'roads',
            time_start: null,
            time_end: null,
          },
        ],
      },
    ],
  }
}

async function goTo(user: ReturnType<typeof userEvent.setup>, text: string) {
  // `find`, not `get`: the app renders a boot state until the session resolves.
  await user.type(await screen.findByLabelText('Place or coordinates'), text)
  await user.click(screen.getByRole('button', { name: 'Go' }))
}

beforeEach(() => {
  mapRef.getZoom.mockReturnValue(5)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  resetSession()
})

describe('going to a coordinate', () => {
  it('moves the marker there and opens the asset panel', async () => {
    mockFetch({ ...session(), [DRESDEN_URL]: { status: 200, body: groups() } })
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, DRESDEN)

    // Latitude first in, lon/lat out — the swap is the point of the parser.
    const marker = await waitFor(() => {
      const node = document.querySelector('[data-marker]')
      expect(node).toBeTruthy()
      return node!
    })
    expect(marker.getAttribute('data-lon')).toBe('13.7373')
    expect(marker.getAttribute('data-lat')).toBe('51.0504')

    expect(await screen.findByRole('button', { name: 'Details for roads' })).toBeInTheDocument()
  })

  it('flies to the coordinate', async () => {
    mockFetch({ ...session(), [DRESDEN_URL]: { status: 200, body: groups() } })
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, DRESDEN)

    expect(mapRef.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: [13.7373, 51.0504] }),
    )
  })

  it('zooms in when the view is too far out to see a marker', async () => {
    mapRef.getZoom.mockReturnValue(3)
    mockFetch({ ...session(), [DRESDEN_URL]: { status: 200, body: groups() } })
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, DRESDEN)

    expect(mapRef.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 12 }))
  })

  it('keeps a closer zoom rather than pulling the view back', async () => {
    mapRef.getZoom.mockReturnValue(16)
    mockFetch({ ...session(), [DRESDEN_URL]: { status: 200, body: groups() } })
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, DRESDEN)

    expect(mapRef.flyTo).toHaveBeenCalledWith(expect.objectContaining({ zoom: 16 }))
  })

  it('switches to point mode, so the mode switch still describes what a click does', async () => {
    mockFetch({ ...session(), [DRESDEN_URL]: { status: 200, body: groups() } })
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await screen.findByRole('radio', { name: 'Navigate' }))
    expect(screen.getByRole('radio', { name: 'Navigate' })).toHaveAttribute('aria-checked', 'true')

    await goTo(user, DRESDEN)

    expect(screen.getByRole('radio', { name: 'Point' })).toHaveAttribute('aria-checked', 'true')
  })

  it('still goes there when nothing covers the coordinate', async () => {
    // No panel and no error, exactly as for a click on empty space
    // (specs/map.md). The marker and the map having moved are the feedback.
    mockFetch({ ...session(), [EMPTY_URL]: { status: 200, body: { groups: [] } } })
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, '0, 0')

    await waitFor(() => expect(mapRef.flyTo).toHaveBeenCalled())
    expect(document.querySelector('[data-marker]')).toBeTruthy()
    expect(screen.queryByRole('complementary', { name: 'Assets at this point' })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('when the coordinate cannot be read', () => {
  it('says so when the text is neither a coordinate nor a place, and does not move', async () => {
    mockFetch({
      ...session(),
      'GET /api/places/search?q=Dresden': { status: 200, body: { results: [] } },
    })
    const user = userEvent.setup()
    renderApp('/')

    // Typed, not `goTo`: an address search is debounced, so Go pressed before
    // the answer arrives has nothing to report yet.
    await user.type(await screen.findByLabelText('Place or coordinates'), 'Dresden')
    expect(await screen.findByText('No place found.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Go' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/No place found/)
    expect(mapRef.flyTo).not.toHaveBeenCalled()
    expect(document.querySelector('[data-marker]')).toBeFalsy()
  })

  it('names the value that is out of range', async () => {
    mockFetch(session())
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, '91, 13.7373')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Latitude must be between -90 and 90/,
    )
    expect(mapRef.flyTo).not.toHaveBeenCalled()
  })

  it('marks the field invalid and clears that as soon as it is edited', async () => {
    mockFetch(session())
    const user = userEvent.setup()
    renderApp('/')

    // An out-of-range pair, not a word: a word is an address now, and an
    // address that finds nothing is a different message.
    await goTo(user, '91, 13.7373')
    const field = await screen.findByLabelText('Place or coordinates')
    expect(field).toHaveAttribute('aria-invalid', 'true')

    await user.type(field, '1')

    expect(field).not.toHaveAttribute('aria-invalid')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('searching for a place', () => {
  const BEIRUT = {
    name: 'Beirut, Lebanon',
    lat: 33.8938,
    lon: 35.5018,
    bbox: [35.4, 33.8, 35.6, 34.0],
  }
  const FOUND = 'GET /api/places/search?q=Beirut'

  function nothingAt(lon: number, lat: number) {
    return { [`GET /api/map/assets?lon=${lon}&lat=${lat}`]: { status: 200, body: { groups: [] } } }
  }

  it('asks the geocoder once typing pauses, not once per letter', async () => {
    const { calls } = mockFetch({
      ...session(),
      [FOUND]: { status: 200, body: { results: [BEIRUT] } },
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await screen.findByLabelText('Place or coordinates'), 'Beirut')

    expect(await screen.findByRole('option', { name: /Beirut, Lebanon/ })).toBeInTheDocument()
    // Six letters, one search. The error state would hide extra calls, so the
    // count is what is asserted rather than the absence of a failure.
    expect(calls.filter((call) => call.startsWith('GET /api/places/search'))).toEqual([FOUND])
  })

  it('never asks the geocoder about a coordinate', async () => {
    const { calls } = mockFetch({ ...session(), ...nothingAt(13.7373, 51.0504) })
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await screen.findByLabelText('Place or coordinates'), '51.0504, 13.7373')
    await user.click(screen.getByRole('button', { name: 'Go' }))

    await waitFor(() => expect(mapRef.flyTo).toHaveBeenCalled())
    expect(calls.filter((call) => call.startsWith('GET /api/places/search'))).toEqual([])
  })

  it('frames the place, drops the marker, and looks up what is there', async () => {
    mockFetch({
      ...session(),
      [FOUND]: { status: 200, body: { results: [BEIRUT] } },
      ...nothingAt(35.5018, 33.8938),
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await screen.findByLabelText('Place or coordinates'), 'Beirut')
    await user.click(await screen.findByRole('option', { name: /Beirut, Lebanon/ }))

    // The extent is a better frame than any fixed zoom, and FIT caps how deep
    // it may go.
    await waitFor(() =>
      expect(mapRef.fitBounds).toHaveBeenCalledWith(
        [
          [35.4, 33.8],
          [35.6, 34.0],
        ],
        expect.objectContaining({ maxZoom: 16 }),
      ),
    )
    expect(document.querySelector('[data-marker]')).toBeTruthy()
  })

  it('flies to a place that has no extent', async () => {
    mockFetch({
      ...session(),
      [FOUND]: { status: 200, body: { results: [{ ...BEIRUT, bbox: null }] } },
      ...nothingAt(35.5018, 33.8938),
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await screen.findByLabelText('Place or coordinates'), 'Beirut')
    await user.click(await screen.findByRole('option', { name: /Beirut, Lebanon/ }))

    await waitFor(() => expect(mapRef.flyTo).toHaveBeenCalled())
    expect(mapRef.fitBounds).not.toHaveBeenCalled()
  })

  it('picks with the keyboard', async () => {
    mockFetch({
      ...session(),
      [FOUND]: { status: 200, body: { results: [BEIRUT] } },
      ...nothingAt(35.5018, 33.8938),
    })
    const user = userEvent.setup()
    renderApp('/')

    const field = await screen.findByLabelText('Place or coordinates')
    await user.type(field, 'Beirut')
    await screen.findByRole('option', { name: /Beirut, Lebanon/ })

    await user.keyboard('{ArrowDown}{Enter}')

    await waitFor(() => expect(mapRef.fitBounds).toHaveBeenCalled())
  })

  it('asks once when address search is switched off, not once per letter', async () => {
    const { calls } = mockFetch({
      ...session(),
      'GET /api/places/search?q=Bei': { status: 503, body: {} },
      'GET /api/places/search?q=Beirut': { status: 503, body: {} },
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await screen.findByLabelText('Place or coordinates'), 'Bei')
    expect(await screen.findByText('Address search is unavailable.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Place or coordinates'), 'rut')

    // A service that is off will not be on three keystrokes later.
    expect(calls.filter((call) => call.startsWith('GET /api/places/search'))).toHaveLength(1)
  })
})

describe('arriving with an area in the link', () => {
  it('frames it once', async () => {
    mockFetch(session())
    renderApp('/map?place=Beirut&bbox=35.4,33.8,35.6,34.0')

    await waitFor(() =>
      expect(mapRef.fitBounds).toHaveBeenCalledWith(
        [
          [35.4, 33.8],
          [35.6, 34.0],
        ],
        expect.objectContaining({ maxZoom: 16 }),
      ),
    )
    expect(mapRef.fitBounds).toHaveBeenCalledTimes(1)
  })

  it('says so and shows everything when the area cannot be read', async () => {
    // Silently widening someone's link from one city to the whole world looks
    // like a broken filter.
    mockFetch(session())
    renderApp('/map?bbox=nonsense')

    expect(await screen.findByText(/area could not be read/)).toBeInTheDocument()
    expect(mapRef.fitBounds).not.toHaveBeenCalled()
  })
})
