import { getChatTurnCreateUrl } from '@/api/generated/chat/chat'
import type { AskContextRequest, ChatTurnEvent } from '@/api/generated/model'
import { fetchWithSession } from '@/api/http-client'

/**
 * Asking one question, and reading the answer as it streams.
 *
 * The one call in the app that does not go through a generated function: the
 * generated `chatTurnCreate` waits for the whole body and parses it as JSON,
 * and an answer is a stream of server-sent events. So the URL and every type
 * still come from the generated client (CLAUDE.md), and only the reading is
 * done here. `fetchWithSession` carries the session as for any other call,
 * renewal on a 401 included.
 *
 * EventSource would read the stream for us, but it can only GET and cannot
 * send the access token, which lives in memory rather than in a cookie.
 */

/** The backend refused the question before anything streamed. */
export class TurnRefused extends Error {
  /** The HTTP status, or 0 when the backend did not answer at all. */
  readonly status: number

  constructor(status: number) {
    super(`The question was refused with ${status}`)
    this.name = 'TurnRefused'
    this.status = status
  }
}

/**
 * The answer's events, in order, until the backend ends the stream.
 *
 * Throws `TurnRefused` before the first event when the backend answers with a
 * status instead of a stream. Aborting `signal` stops the read and makes the
 * backend drop the agent's stream too.
 */
export async function* askTurn(
  sessionId: string,
  prompt: string,
  context: AskContextRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatTurnEvent> {
  let response: Response
  try {
    response = await fetchWithSession(getChatTurnCreateUrl(sessionId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ prompt, context }),
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new TurnRefused(0)
  }

  if (!response.ok || !response.body) throw new TurnRefused(response.status)
  yield* readEvents(response.body)
}

/**
 * Server-sent events from a byte stream, each `data:` line read as one event.
 *
 * The backend writes the whole event, `event` field included, as one JSON
 * line (backend/apps/chat/sse.py), so the `event:` line is not needed here.
 * A line that is not JSON is skipped rather than fatal: the stream's last
 * event says whether the answer is whole.
 */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatTurnEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let ended = false

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) {
        ended = true
        break
      }
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const raw of lines) {
        const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw
        if (!line.startsWith('data:')) continue
        try {
          yield JSON.parse(line.slice(5).trimStart()) as ChatTurnEvent
        } catch {
          // Not JSON: see above.
        }
      }
    }
  } finally {
    // A reader that stops early (the last event came, or the caller left)
    // cancels the stream, so the connection is not held open behind it.
    if (!ended) await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
