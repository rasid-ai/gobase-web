/** Ask on the Atlas page: specs/ask.md, docs/adr/023 and docs/adr/025. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getCatalogDatasetListUrl, getCatalogDocumentPdfUrl } from '@/api/generated/catalog/catalog'
import {
  getChatSessionDeleteUrl,
  getChatSessionListUrl,
  getChatSessionRetrieveUrl,
  getChatTurnCreateUrl,
} from '@/api/generated/chat/chat'
import { getMapAssetDataUrl, getMapAssetDetailUrl } from '@/api/generated/map/map'
import type { Bbox } from '@/features/places/bbox'
import { serializeBbox } from '@/features/places/bbox'
import { PAGE_SIZE } from '@/features/workspace/useAssetFeatures'
import { windowFor } from '@/features/workspace/view'
import { type Route, fakeTab, mockFetch, openStream, renderApp, resetSession } from '@/test/harness'

/** Where the stub map is looking. */
const HOME: Bbox = [35.4, 33.7, 35.7, 34.0]
const camera = {
  fitBounds: vi.fn(),
  flyTo: vi.fn(),
  getZoom: () => 8.5,
  getBounds: () => ({
    getWest: () => HOME[0],
    getSouth: () => HOME[1],
    getEast: () => HOME[2],
    getNorth: () => HOME[3],
  }),
}

/** MapLibre needs WebGL, which jsdom lacks; this records what the page draws instead. */
vi.mock('react-map-gl/maplibre', async () => {
  const { useEffect } = await import('react')
  function StubMap({
    children,
    onClick,
    onLoad,
    ref,
  }: {
    children?: React.ReactNode
    onClick?: (event: { lngLat: { lng: number; lat: number } }) => void
    onLoad?: () => void
    ref?: { current: unknown }
  }) {
    if (ref) ref.current = camera
    useEffect(() => {
      onLoad?.()
    }, [onLoad])
    return (
      <div data-map>
        <button type="button" onClick={() => onClick?.({ lngLat: { lng: 35.5, lat: 33.85 } })}>
          map surface
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
    Layer: ({ id, layout }: { id: string; layout?: { visibility?: string } }) => (
      <div data-layer={id} data-visibility={layout?.visibility ?? 'visible'} />
    ),
    Marker: () => <div data-marker />,
  }
})
vi.mock('@/features/workspace/DrawArea', () => ({ DrawArea: () => null }))

/** What `newSessionId` makes when the random bytes are all zero. */
const SESSION = '00000000-0000-4000-8000-000000000000'
const STORED = '6f1c2a8e-4b7d-4c1e-9a3f-2d5b8e7c1a90'
const DOC = 'cccccccc-dddd-eeee-ffff-000000000000'
const ROADS = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

const LIST = `GET ${getChatSessionListUrl()}`
const TURN = `POST ${getChatTurnCreateUrl(SESSION)}`
const QUESTION = 'What does the airport report say about security?'

function sse(event: Record<string, unknown>): string {
  return `event: ${event.event}\ndata: ${JSON.stringify(event)}\n\n`
}

function detail(id: string, name: string, data_type: string) {
  return { asset_id: id, name, data_type, metadata: {}, footprint: null }
}

function routes(extra: Record<string, Route> = {}): Record<string, Route> {
  return {
    'POST /api/auth/refresh': { status: 200, body: { access: 'access-token' } },
    'GET /api/auth/me': { status: 200, body: { username: 'viewer1', role: 'viewer' } },
    [LIST]: { status: 200, body: { results: [] } },
    [`GET ${getMapAssetDetailUrl(DOC)}`]: {
      status: 200,
      body: detail(DOC, 'Airport report', 'document'),
    },
    [`GET ${getMapAssetDetailUrl(ROADS)}`]: { status: 200, body: detail(ROADS, 'roads', 'vector') },
    ...extra,
  }
}

async function openAsk(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^Open Ask/ }))
  return screen.findByRole('complementary', { name: 'Ask' })
}

async function askQuestion(user: ReturnType<typeof userEvent.setup>, panel: HTMLElement) {
  await user.type(within(panel).getByLabelText('Question'), `${QUESTION}{Enter}`)
}

beforeEach(() => {
  camera.fitBounds.mockClear()
  // Zero random bytes, so the new session's id is known.
  vi.spyOn(crypto, 'getRandomValues').mockImplementation((array) => array)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetSession()
})

describe('the Ask panel', () => {
  it('opens from the toggle on an empty session, with questions to start from', async () => {
    mockFetch(routes())
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)

    expect(within(panel).getByRole('heading', { name: 'New chat' })).toBeTruthy()
    expect(within(panel).getByRole('button', { name: QUESTION })).toBeTruthy()
    expect(within(panel).getByText('Asking about · the current view')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Open Ask/ })).toBeNull()
  })

  it('says Ask is unavailable, and offers no way to send, when the backend has no agent', async () => {
    mockFetch(routes({ [LIST]: { status: 503, body: { detail: 'Ask is not configured' } } }))
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)

    expect(await within(panel).findByText('Ask is unavailable.')).toBeTruthy()
    expect((within(panel).getByLabelText('Question') as HTMLTextAreaElement).disabled).toBe(true)
  })
})

describe('asking a question', () => {
  it('streams the answer, cites its sources, and sends what the map is looking at', async () => {
    // Everything the tools returned; the answer cites only the report.
    const report = {
      kind: 'passage',
      handle: 'P1',
      asset_id: DOC,
      name: 'Airport report',
      data_type: 'document',
      chunk_id: 'c-1',
      page: 3,
    }
    const roads = {
      kind: 'asset',
      handle: 'A1',
      asset_id: ROADS,
      name: 'roads',
      data_type: 'vector',
    }
    const text = 'It describes security as **adequate** [P1], quoting the brief [sic].'
    const { fetchMock } = mockFetch(
      routes({
        [`GET ${getCatalogDatasetListUrl({ lon: 35.5, lat: 33.85 })}`]: {
          status: 200,
          body: { results: [] },
        },
        // The chip renders from the reference: no detail request is needed for it.
        [`GET ${getMapAssetDetailUrl(ROADS)}`]: { status: 404 },
        [TURN]: {
          status: 200,
          stream: [
            sse({ event: 'step', tool: 'doc_passages', status: 'started', note: 'Reading' }),
            sse({ event: 'reference', reference: roads }),
            sse({ event: 'reference', reference: report }),
            sse({ event: 'text', delta: 'It describes security as **adequate** [P1]' }),
            sse({
              event: 'done',
              text,
              references: [
                { ...roads, cited: false },
                { ...report, cited: true },
              ],
            }),
          ],
        },
      }),
    )
    const user = userEvent.setup()
    renderApp('/map')

    await user.click(await screen.findByRole('button', { name: 'map surface' }))
    const panel = await openAsk(user)
    expect(within(panel).getByText('Asking about · this point')).toBeTruthy()
    await askQuestion(user, panel)

    expect(await within(panel).findByText('adequate')).toBeTruthy()
    // The marker is a numbered mark, and the chip carries the same number.
    const mark = await within(panel).findByRole('button', { name: 'Citation 1: Airport report' })
    expect(mark.textContent).toBe('1')
    expect(within(panel).queryByText(/\[P1\]/)).toBeNull()
    expect(within(panel).getByText(/quoting the brief \[sic\]\./)).toBeTruthy()
    expect(
      within(panel).getByRole('button', { name: /^1\s*Airport report\s*document p\. 3$/ }),
    ).toBeTruthy()
    // The roads were returned but not cited: no chip.
    expect(within(panel).queryByRole('button', { name: /roads/ })).toBeNull()
    // No tool trace in the UI (context/ui-rules.md).
    expect(within(panel).queryByText('Reading')).toBeNull()

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/turns'))!
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({
      prompt: QUESTION,
      context: { viewport: HOME, point: [35.5, 33.85] },
    })
    // The box is empty for the next question, which is now a follow-up.
    expect(within(panel).getByPlaceholderText('Ask a follow-up…')).toBeTruthy()
  })

  it("opens a cited document's PDF at the cited page, from its mark or its chip", async () => {
    const tab = fakeTab()
    const passage = {
      kind: 'passage',
      handle: 'P1',
      asset_id: DOC,
      chunk_id: 'c1',
      page: 4,
      data_type: 'document',
      name: 'Airport report',
      cited: true,
    }
    mockFetch(
      routes({
        [TURN]: {
          status: 200,
          stream: [sse({ event: 'done', text: 'Screening is fast [P1].', references: [passage] })],
        },
        [`GET ${getCatalogDocumentPdfUrl(DOC)}`]: {
          status: 200,
          blob: new Blob(['%PDF-'], { type: 'application/pdf' }),
        },
      }),
    )
    const user = userEvent.setup()
    renderApp('/map')
    const panel = await openAsk(user)
    await askQuestion(user, panel)

    // The chip, not the map's pane: a document has nothing to draw.
    await user.click(await within(panel).findByRole('button', { name: /^1\s*Airport report/ }))
    expect(window.open).toHaveBeenCalledWith('', '_blank')
    await waitFor(() => expect(tab.location.href).toBe('blob:pdf#page=4'))
    expect(screen.queryByRole('heading', { name: 'Airport report' })).toBeNull()

    await user.click(within(panel).getByRole('button', { name: 'Citation 1: Airport report' }))
    expect(window.open).toHaveBeenCalledTimes(2)
  })

  it('shows a citation as the asset it cites, from its mark in the text or its chip', async () => {
    const reference = { kind: 'asset', handle: 'A1', asset_id: DOC, cited: true }
    mockFetch(
      routes({
        [TURN]: {
          status: 200,
          stream: [sse({ event: 'done', text: 'See the report [A1].', references: [reference] })],
        },
      }),
    )
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)
    // No name came with the reference, so the chip reads the catalog for it.
    // One chip: a cited asset is not repeated in a box below.
    expect(
      await within(panel).findAllByRole('button', { name: /^1\s*Airport report/ }),
    ).toHaveLength(1)
    await user.click(within(panel).getByRole('button', { name: 'Citation 1' }))

    const pane = await screen.findByRole('complementary', { name: 'Selected asset' })
    expect(within(pane).getByText('Airport report')).toBeTruthy()
  })

  it('draws a layer from the answer, and its chip hides and shows it', async () => {
    const layer = { kind: 'layer', asset_id: ROADS, bbox: HOME, total: 14 }
    mockFetch(
      routes({
        [TURN]: {
          status: 200,
          stream: [
            sse({ event: 'reference', reference: layer }),
            sse({ event: 'done', text: 'There are 14 roads.', references: [layer] }),
          ],
        },
        [`GET ${getMapAssetDataUrl(ROADS, {
          limit: PAGE_SIZE,
          bbox: serializeBbox(windowFor(HOME, 8.5)),
        })}`]: {
          status: 200,
          body: { asset_id: ROADS, count: 0, next_cursor: null, features: [] },
        },
      }),
    )
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)

    await waitFor(() => {
      expect(document.querySelector(`[data-source^="asset-${ROADS}~"]`)).toBeTruthy()
    })
    const chip = await within(panel).findByRole('button', { name: /roads · answer's area\s*14/ })
    expect(chip.getAttribute('aria-pressed')).toBe('true')

    await user.click(chip)

    expect(chip.getAttribute('aria-pressed')).toBe('false')
    expect(
      document.querySelector(`[data-layer^="asset-${ROADS}~"][data-layer$="-fill"]`)?.getAttribute('data-visibility'),
    ).toBe('none')
  })

  it('moves the map to a frame the answer gives', async () => {
    const frame = { kind: 'frame', bbox: [35.1, 33.0, 36.6, 34.7] }
    mockFetch(
      routes({
        [TURN]: {
          status: 200,
          stream: [
            sse({ event: 'reference', reference: frame }),
            sse({ event: 'done', text: 'Here.', references: [frame] }),
          ],
        },
      }),
    )
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)

    await waitFor(() => expect(camera.fitBounds).toHaveBeenCalled())
    expect(camera.fitBounds.mock.calls[0][0]).toEqual([
      [35.1, 33.0],
      [36.6, 34.7],
    ])
    expect(await within(panel).findByRole('button', { name: 'Framed to the answer' })).toBeTruthy()
  })
})

describe('when an answer does not finish', () => {
  it('marks it cut off, never whole, and Try again asks again', async () => {
    const answers = routes({
      [TURN]: {
        status: 200,
        stream: [
          sse({ event: 'text', delta: 'It describes security as' }),
          sse({ event: 'error', message: 'The answer was cut off.', incomplete: true }),
        ],
      },
    })
    mockFetch(answers)
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)

    expect(await within(panel).findByText('The answer was cut off.')).toBeTruthy()
    expect(within(panel).getByText('It describes security as')).toBeTruthy()

    answers[TURN] = {
      status: 200,
      stream: [sse({ event: 'done', text: 'It describes security as adequate.', references: [] })],
    }
    await user.click(within(panel).getByRole('button', { name: 'Try again' }))

    expect(await within(panel).findByText('It describes security as adequate.')).toBeTruthy()
    expect(within(panel).queryByText('The answer was cut off.')).toBeNull()
    // The question is asked again in its place, not added below.
    expect(within(panel).getAllByRole('article')).toHaveLength(1)
  })

  it('marks a stream that ends with no last event as cut off', async () => {
    mockFetch(routes({ [TURN]: { status: 200, stream: [sse({ event: 'text', delta: 'It' })] } }))
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)

    expect(await within(panel).findByText('The answer was cut off.')).toBeTruthy()
  })

  it('stops when asked to, and says so', async () => {
    const stream = openStream()
    mockFetch(routes({ [TURN]: { status: 200, stream: stream.stream } }))
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)
    stream.send(sse({ event: 'text', delta: 'It describes' }))
    expect(await within(panel).findByText('Answering')).toBeTruthy()

    await user.click(within(panel).getByRole('button', { name: 'Stop' }))

    expect(await within(panel).findByText('The answer was stopped.')).toBeTruthy()
    expect(within(panel).queryByText('Answering')).toBeNull()
  })

  it('puts a refused question back in the box, and says why', async () => {
    mockFetch(
      routes({ [TURN]: { status: 502, body: { detail: 'The Ask service returned an error' } } }),
    )
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)

    expect(
      await screen.findByText("Couldn't send the question. The Ask service returned 502."),
    ).toBeTruthy()
    expect((within(panel).getByLabelText('Question') as HTMLTextAreaElement).value).toBe(QUESTION)
    expect(within(panel).queryAllByRole('article')).toHaveLength(0)
  })
})

describe('an answer that ends while the panel is closed', () => {
  it('keeps streaming, and puts a dot on the toggle', async () => {
    const stream = openStream()
    mockFetch(routes({ [TURN]: { status: 200, stream: stream.stream } }))
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await askQuestion(user, panel)
    await user.click(within(panel).getByRole('button', { name: 'Close Ask' }))
    expect(screen.getByRole('button', { name: 'Open Ask' })).toBeTruthy()

    stream.send(sse({ event: 'done', text: 'It is adequate.', references: [] }))
    stream.end()

    expect(await screen.findByRole('button', { name: 'Open Ask, an answer is ready' })).toBeTruthy()
    const reopened = await openAsk(user)
    expect(within(reopened).getByText('It is adequate.')).toBeTruthy()
  })
})

describe('sessions', () => {
  const row = {
    session_id: STORED,
    title: 'Flood extent along the eastern wadi',
    created_at: '2026-10-31T09:00:00Z',
    updated_at: '2026-10-31T09:05:00Z',
  }

  it('reopens a stored session with its turns, and deletes one', async () => {
    const answers = routes({
      [LIST]: { status: 200, body: { results: [row] } },
      [`GET ${getChatSessionRetrieveUrl(STORED)}`]: {
        status: 200,
        body: {
          ...row,
          turns: [
            {
              prompt: 'Where did the wadi flood?',
              text: 'Along the eastern bank [A2].',
              references: [
                {
                  kind: 'asset',
                  handle: 'A1',
                  asset_id: DOC,
                  name: 'Airport report',
                  cited: false,
                },
                { kind: 'asset', handle: 'A2', asset_id: ROADS, name: 'roads', cited: true },
              ],
              incomplete: false,
            },
          ],
        },
      },
      [`DELETE ${getChatSessionDeleteUrl(STORED)}`]: { status: 204 },
    })
    mockFetch(answers)
    const user = userEvent.setup()
    renderApp('/map')

    const panel = await openAsk(user)
    await user.click(within(panel).getByRole('button', { name: 'Sessions' }))
    await user.click(await within(panel).findByRole('button', { name: row.title }))

    expect(await within(panel).findByText(/Along the eastern bank/)).toBeTruthy()
    expect(within(panel).getByRole('heading', { name: row.title })).toBeTruthy()
    // A stored turn shows its cited reference, numbered, and not the other.
    expect(within(panel).getByRole('button', { name: 'Citation 1: roads' })).toBeTruthy()
    expect(within(panel).getAllByRole('button', { name: /^1\s*roads/ })).toHaveLength(1)
    expect(within(panel).queryByRole('button', { name: /Airport report/ })).toBeNull()

    await user.click(within(panel).getByRole('button', { name: 'Sessions' }))
    answers[LIST] = { status: 200, body: { results: [] } }
    await user.click(await within(panel).findByRole('button', { name: `Delete ${row.title}` }))

    expect(await within(panel).findByText('No sessions yet')).toBeTruthy()
    // The open session was the deleted one, so the conversation starts afresh.
    await user.click(within(panel).getByRole('button', { name: 'Sessions' }))
    expect(within(panel).getByRole('heading', { name: 'New chat' })).toBeTruthy()
  })
})
