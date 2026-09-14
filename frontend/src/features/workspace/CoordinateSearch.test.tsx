/** Going to a typed coordinate: specs/map.md. */

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
  await user.type(await screen.findByLabelText('Latitude, longitude'), text)
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
  it('explains the format and does not move the map', async () => {
    mockFetch(session())
    const user = userEvent.setup()
    renderApp('/')

    await goTo(user, 'Dresden')

    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter latitude, longitude/)
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

    await goTo(user, 'nope')
    const field = await screen.findByLabelText('Latitude, longitude')
    expect(field).toHaveAttribute('aria-invalid', 'true')

    await user.type(field, '1')

    expect(field).not.toHaveAttribute('aria-invalid')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
