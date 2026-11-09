/** Reading an answer's server-sent events (backend/apps/chat/sse.py writes them). */

import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ChatTurnEvent } from '@/api/generated/model'
import { mockFetch, resetSession } from '@/test/harness'

import { TurnRefused, askTurn, readEvents } from './turnStream'

const SESSION = '6f1c2a8e-4b7d-4c1e-9a3f-2d5b8e7c1a90'
const URL = `POST /api/chat/sessions/${SESSION}/turns`

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  })
}

async function collect(events: AsyncIterable<ChatTurnEvent>) {
  const seen: ChatTurnEvent[] = []
  for await (const event of events) seen.push(event)
  return seen
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetSession()
})

describe('readEvents', () => {
  it('reads one event per data line', async () => {
    const events = await collect(
      readEvents(
        streamOf([
          'event: text\ndata: {"event":"text","delta":"It"}\n\n',
          'event: text\ndata: {"event":"text","delta":" says"}\n\n',
        ]),
      ),
    )

    expect(events).toEqual([
      { event: 'text', delta: 'It' },
      { event: 'text', delta: ' says' },
    ])
  })

  it('puts back together an event the network split, even mid-character', async () => {
    // "é" is two bytes in UTF-8; the split lands between them.
    const bytes = new TextEncoder().encode('data: {"event":"text","delta":"café"}\r\n\r\n')
    const cut = bytes.indexOf(0xa9)
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut))
        controller.enqueue(bytes.slice(cut))
        controller.close()
      },
    })

    expect(await collect(readEvents(body))).toEqual([{ event: 'text', delta: 'café' }])
  })

  it('skips a line that is not JSON', async () => {
    const events = await collect(
      readEvents(streamOf(['data: not json\n\n', 'data: {"event":"text","delta":"ok"}\n\n'])),
    )

    expect(events).toEqual([{ event: 'text', delta: 'ok' }])
  })
})

describe('askTurn', () => {
  it('posts the question and the map context as JSON', async () => {
    const { fetchMock } = mockFetch({
      [URL]: { status: 200, stream: ['data: {"event":"done","text":"","references":[]}\n\n'] },
    })

    const events = await collect(
      askTurn(SESSION, 'What is here?', { point: [35.5, 33.9] }, new AbortController().signal),
    )

    expect(events).toEqual([{ event: 'done', text: '', references: [] }])
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({
      prompt: 'What is here?',
      context: { point: [35.5, 33.9] },
    })
  })

  it('throws the status when the backend refuses before streaming', async () => {
    mockFetch({ [URL]: { status: 502, body: { detail: 'The Ask service returned an error' } } })

    const attempt = collect(askTurn(SESSION, 'Hi', {}, new AbortController().signal))

    await expect(attempt).rejects.toEqual(new TurnRefused(502))
  })

  it('throws status 0 when the backend does not answer at all', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    const attempt = collect(askTurn(SESSION, 'Hi', {}, new AbortController().signal))

    await expect(attempt).rejects.toMatchObject({ status: 0 })
  })
})
