import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { chatSessionRetrieve, getChatSessionListQueryKey } from '@/api/generated/chat/chat'
import type { AskContextRequest, ChatReference, ChatSessionDetail } from '@/api/generated/model'
import { useToast } from '@/components/ui/toast'

import { newSessionId } from './sessionId'
import { TurnRefused, askTurn } from './turnStream'

/**
 * The conversation on the Atlas page: one session, its turns, and the answer
 * that may be streaming into it.
 *
 * It lives with the page, not the panel, so closing the panel neither stops
 * an answer nor forgets it — and an answer that ends while the panel is
 * closed lights the toggle's dot. The agent keeps the history (docs/adr/023);
 * this holds only what is on screen, and reopening a session reads it back.
 */

export type AskTurn = {
  /** A local key for rendering. Turns have no id of their own in the API. */
  key: number
  prompt: string
  text: string
  references: ChatReference[]
  status: 'streaming' | 'done' | 'incomplete'
  /** Why it stopped, as the API said it, when it is incomplete. */
  message: string | null
}

export type Conversation = {
  sessionId: string
  /** The stored title of a reopened session; a new one is titled by its first question. */
  title: string | null
  turns: AskTurn[]
  /** When it last changed, for the header's "4 min ago". */
  updatedAt: string | null
  /** A stored session is being read. */
  loading: boolean
}

/** Stopped by the user, so not the API's words. */
export const STOPPED = 'The answer was stopped.'
/** The stream ended with no last event: the backend's own words for the same thing. */
export const CUT_OFF = 'The answer was cut off.'

function fresh(): Conversation {
  return { sessionId: newSessionId(), title: null, turns: [], updatedAt: null, loading: false }
}

function refusal(status: number): string {
  return status === 0
    ? "Couldn't send the question. The portal did not answer."
    : `Couldn't send the question. The Ask service returned ${status}.`
}

type Options = {
  /** Whether the panel is showing, so an answer that ends unseen can say so. */
  open: boolean
  /** The map's state at the moment of asking. */
  getContext: () => AskContextRequest
  /** A reference arrived while an answer streamed — the page frames or draws it. */
  onReference: (reference: ChatReference) => void
}

export function useAsk({ open, getContext, onReference }: Options) {
  const queryClient = useQueryClient()
  const toast = useToast()

  const [conversation, setConversation] = useState<Conversation>(fresh)
  const [streaming, setStreaming] = useState(false)
  const [unread, setUnread] = useState(false)
  // The composer's text. Here rather than in the panel, so a refused
  // question can be put back, and a draft survives closing the panel.
  const [draft, setDraft] = useState('')

  const session = useRef(conversation.sessionId)
  const abort = useRef<AbortController | null>(null)
  const keys = useRef(0)
  const opening = useRef(0)
  const latest = useRef({ open, getContext, onReference })
  useEffect(() => {
    latest.current = { open, getContext, onReference }
  })

  // Leaving the page stops the answer; the agent keeps what it had.
  useEffect(() => () => abort.current?.abort(), [])

  /** Change the conversation, unless the user has moved to another session since. */
  const update = useCallback(
    (sessionId: string, change: (current: Conversation) => Conversation) => {
      setConversation((current) => (current.sessionId === sessionId ? change(current) : current))
    },
    [],
  )

  const run = useCallback(
    async (sessionId: string, prompt: string) => {
      const key = ++keys.current
      const controller = new AbortController()
      abort.current = controller
      setStreaming(true)
      setDraft('')
      update(sessionId, (current) => ({
        ...current,
        turns: [
          ...current.turns,
          { key, prompt, text: '', references: [], status: 'streaming', message: null },
        ],
      }))

      const patch = (change: (turn: AskTurn) => AskTurn) =>
        update(sessionId, (current) => ({
          ...current,
          turns: current.turns.map((turn) => (turn.key === key ? change(turn) : turn)),
        }))

      let streamed = false
      try {
        let ended = false
        const events = askTurn(sessionId, prompt, latest.current.getContext(), controller.signal)
        for await (const event of events) {
          streamed = true
          if (event.event === 'text') {
            patch((turn) => ({ ...turn, text: turn.text + event.delta }))
          } else if (event.event === 'reference') {
            patch((turn) => ({ ...turn, references: [...turn.references, event.reference] }))
            if (session.current === sessionId) latest.current.onReference(event.reference)
          } else if (event.event === 'done') {
            // The checked whole replaces what streamed: the agent may have
            // dropped a reference it could not stand behind.
            patch((turn) => ({
              ...turn,
              text: event.text,
              references: event.references,
              status: 'done',
            }))
            ended = true
          } else if (event.event === 'error') {
            patch((turn) => ({ ...turn, status: 'incomplete', message: event.message }))
            ended = true
          }
          // `step` is the agent looking something up. The panel shows only
          // that it is answering: no tool trace in the UI (context/ui-rules.md).
          if (ended) break
        }
        if (!ended) patch((turn) => ({ ...turn, status: 'incomplete', message: CUT_OFF }))
        streamed = true
      } catch (error) {
        if (error instanceof TurnRefused) {
          // Nothing streamed: the question goes back in the box, as if it
          // had never been sent.
          update(sessionId, (current) => ({
            ...current,
            turns: current.turns.filter((turn) => turn.key !== key),
          }))
          if (session.current === sessionId) setDraft(prompt)
          toast.show(refusal(error.status))
        } else {
          streamed = true
          const message = controller.signal.aborted ? STOPPED : CUT_OFF
          patch((turn) => ({ ...turn, status: 'incomplete', message }))
        }
      } finally {
        if (abort.current === controller) {
          abort.current = null
          setStreaming(false)
        }
      }

      if (!streamed) return
      update(sessionId, (current) => ({ ...current, updatedAt: new Date().toISOString() }))
      // A new session now exists on the agent; an old one has a new time.
      void queryClient.invalidateQueries({ queryKey: getChatSessionListQueryKey() })
      if (!latest.current.open && session.current === sessionId) setUnread(true)
    },
    [queryClient, toast, update],
  )

  const send = useCallback(
    (prompt: string) => {
      const question = prompt.trim()
      if (!question || abort.current) return
      void run(session.current, question)
    },
    [run],
  )

  const stop = useCallback(() => abort.current?.abort(), [])

  /**
   * Ask an incomplete question again, in its place.
   *
   * The panel offers it on the last turn only. The agent's session keeps the
   * stopped attempt too, so a reopened session shows both.
   */
  const retry = useCallback(
    (turn: AskTurn) => {
      if (abort.current || turn.status !== 'incomplete') return
      const sessionId = session.current
      update(sessionId, (current) => ({
        ...current,
        turns: current.turns.filter((one) => one.key !== turn.key),
      }))
      void run(sessionId, turn.prompt)
    },
    [run, update],
  )

  /** Drop what is streaming and anything being opened. */
  const leave = useCallback(() => {
    abort.current?.abort()
    abort.current = null
    opening.current += 1
    setStreaming(false)
  }, [])

  const newChat = useCallback(() => {
    leave()
    const next = fresh()
    session.current = next.sessionId
    setConversation(next)
    setDraft('')
  }, [leave])

  const openSession = useCallback(
    async (sessionId: string) => {
      if (sessionId === session.current && !abort.current) return
      leave()
      const request = opening.current
      session.current = sessionId
      setDraft('')
      setConversation({ sessionId, title: null, turns: [], updatedAt: null, loading: true })

      const giveUp = (message: string) => {
        if (opening.current !== request) return
        toast.show(message)
        const next = fresh()
        session.current = next.sessionId
        setConversation(next)
      }

      try {
        const answer = await chatSessionRetrieve(sessionId)
        if (opening.current !== request) return
        if (answer.status === 200) {
          setConversation(stored(answer.data, () => ++keys.current))
          return
        }
        if (answer.status === 404) {
          void queryClient.invalidateQueries({ queryKey: getChatSessionListQueryKey() })
          giveUp('That chat no longer exists.')
        } else {
          giveUp(`Couldn't open the chat. The Ask service returned ${answer.status}.`)
        }
      } catch {
        giveUp("Couldn't open the chat. The portal did not answer.")
      }
    },
    [leave, queryClient, toast],
  )

  /** A session was deleted. If it is the one on screen, start a new one. */
  const forget = useCallback(
    (sessionId: string) => {
      if (sessionId === session.current) newChat()
    },
    [newChat],
  )

  const markRead = useCallback(() => setUnread(false), [])

  return {
    conversation,
    streaming,
    unread,
    draft,
    setDraft,
    send,
    stop,
    retry,
    newChat,
    openSession,
    forget,
    markRead,
  }
}

export type Ask = ReturnType<typeof useAsk>

/** A stored session as the panel holds it. */
function stored(detail: ChatSessionDetail, key: () => number): Conversation {
  return {
    sessionId: detail.session_id,
    title: detail.title || null,
    updatedAt: detail.updated_at,
    loading: false,
    turns: detail.turns.map((turn) => ({
      key: key(),
      prompt: turn.prompt,
      text: turn.text,
      references: turn.references,
      status: turn.incomplete ? 'incomplete' : 'done',
      // The stored turn keeps that it stopped, not why.
      message: turn.incomplete ? CUT_OFF : null,
    })),
  }
}
