import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, History, Square, Trash2, X } from 'lucide-react'
import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import {
  type chatSessionListResponse,
  getChatSessionListQueryKey,
  useChatSessionDelete,
  useChatSessionList,
} from '@/api/generated/chat/chat'
import type { ChatSession } from '@/api/generated/model'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'

import { AnswerText } from './AnswerText'
import { Citations, OutputBox } from './ReferenceChips'
import { groupReferences } from './references'
import type { Ask, AskTurn } from './useAsk'
import { ago, day, useNow } from './when'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/** What "here" is for the next question, in the context line's words. */
export type AskScope = 'area' | 'point' | 'view'

const SCOPE_LABEL: Record<AskScope, string> = {
  area: 'this area',
  point: 'this point',
  view: 'the current view',
}

/** Questions offered on an empty session, from the design. Clicking one asks it. */
const EXAMPLES = [
  'What data is there here?',
  'What does the airport report say about security?',
  'How many health facilities are in this area?',
]

/**
 * The Ask panel: a docked column on the right of the Atlas page
 * (context/ui-rules.md, specs/ask.md).
 *
 * Two views. The conversation — questions, answers, their citations and what
 * they put on the map — over a composer that says what the question will be
 * about. And the session list, behind the history button.
 *
 * Opening the panel reads the session list. That one read is also how the
 * panel knows Ask is unavailable: the backend answers 503 when no agent is
 * set or reachable, and the composer is then disabled with a line saying so.
 */
export function AskPanel({
  ask,
  scope,
  assetSelected,
  onClose,
  onSelectAsset,
  onFrame,
}: {
  ask: Ask
  scope: AskScope
  assetSelected: boolean
  onClose: () => void
  onSelectAsset: (assetId: string) => void
  onFrame: (bbox: [number, number, number, number]) => void
}) {
  const [view, setView] = useState<'chat' | 'sessions'>('chat')
  const sessions = useChatSessionList()
  const unavailable = sessions.data?.status === 503
  const now = useNow()

  const { conversation, streaming } = ask
  const { turns, loading } = conversation
  const title = conversation.title ?? turns[0]?.prompt ?? null

  return (
    <aside
      aria-label="Ask"
      className="flex w-96 shrink-0 flex-col border-l border-border bg-background"
    >
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
        {view === 'chat' && loading ? (
          // The row's flex-1 is the wrapper's, so Close stays at the right edge.
          <div className="min-w-0 flex-1">
            <Skeleton className="h-5 w-full max-w-[12rem]" />
          </div>
        ) : (
          <h2
            className={cn(
              'min-w-0 flex-1 truncate text-[15px]',
              view === 'chat' && !title && 'text-muted-foreground',
            )}
            title={view === 'chat' ? (title ?? undefined) : undefined}
          >
            {view === 'sessions' ? 'Sessions' : (title ?? 'New chat')}
          </h2>
        )}

        {view === 'chat' && streaming ? (
          <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-primary">
            Answering
          </span>
        ) : view === 'chat' && conversation.updatedAt && !loading ? (
          <span className={cn(MICRO, 'shrink-0')}>{ago(conversation.updatedAt, now)}</span>
        ) : null}

        {view === 'sessions' || (turns.length > 0 && !streaming) ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              ask.newChat()
              setView('chat')
            }}
          >
            New chat
          </Button>
        ) : null}

        {!(view === 'chat' && loading) ? (
          <IconButton
            label="Sessions"
            pressed={view === 'sessions'}
            onClick={() => setView(view === 'sessions' ? 'chat' : 'sessions')}
          >
            <History />
          </IconButton>
        ) : null}
        <IconButton label="Close Ask" onClick={onClose}>
          <X />
        </IconButton>
      </header>

      {view === 'sessions' ? (
        <SessionList
          answer={sessions.data}
          failed={sessions.isError}
          onRetry={() => void sessions.refetch()}
          currentId={conversation.sessionId}
          now={now}
          onOpen={(sessionId) => {
            void ask.openSession(sessionId)
            setView('chat')
          }}
          onDeleted={ask.forget}
        />
      ) : (
        <>
          {loading ? (
            <LoadingSession />
          ) : turns.length === 0 ? (
            <div className="flex min-h-0 flex-1 flex-col justify-end gap-4 overflow-y-auto px-4 pb-2">
              {unavailable ? null : <EmptySession onAsk={ask.send} />}
            </div>
          ) : (
            <Turns ask={ask} turns={turns} onSelectAsset={onSelectAsset} onFrame={onFrame} />
          )}

          {/* No composer while a session loads: there is nothing yet to follow up on. */}
          {loading ? null : (
            <footer className="flex shrink-0 flex-col gap-2 px-4 pb-4 pt-2">
              {unavailable ? (
                <p className="text-sm text-muted-foreground">Ask is unavailable.</p>
              ) : (
                <p className={MICRO}>
                  Asking about · {SCOPE_LABEL[scope]}
                  {assetSelected ? ' · 1 asset selected' : ''}
                </p>
              )}
              <Composer
                ask={ask}
                disabled={unavailable}
                placeholder={turns.length > 0 ? 'Ask a follow-up…' : 'Ask about the map…'}
              />
            </footer>
          )}
        </>
      )}
    </aside>
  )
}

function IconButton({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string
  pressed?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      onClick={onClick}
      className={cn(
        'inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-[18px]',
        pressed && 'bg-accent text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function EmptySession({ onAsk }: { onAsk: (question: string) => void }) {
  return (
    <>
      <p className="text-[15px] text-muted-foreground">
        Ask about the data on the map. Answers cite their sources and can add layers to the map.
      </p>
      <ul className="flex flex-col gap-1">
        {EXAMPLES.map((example) => (
          <li key={example}>
            <button
              type="button"
              onClick={() => onAsk(example)}
              className="w-full rounded-md py-1.5 text-left text-[15px] hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {example}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

function LoadingSession() {
  return (
    <div aria-label="Loading the chat" className="flex min-h-0 flex-1 flex-col gap-5 p-4">
      <Skeleton className="ml-auto h-10 w-3/5" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="ml-auto h-10 w-1/2" />
    </div>
  )
}

/**
 * The conversation, oldest first, kept scrolled to the end while it grows —
 * unless the reader has scrolled up to read something, which is left alone.
 */
function Turns({
  ask,
  turns,
  onSelectAsset,
  onFrame,
}: {
  ask: Ask
  turns: AskTurn[]
  onSelectAsset: (assetId: string) => void
  onFrame: (bbox: [number, number, number, number]) => void
}) {
  const scroller = useRef<HTMLDivElement | null>(null)
  const pinned = useRef(true)
  const last = turns.at(-1)
  const growth = `${turns.length}:${last?.text.length ?? 0}:${last?.references.length ?? 0}:${last?.status}`

  useEffect(() => {
    const element = scroller.current
    if (element && pinned.current) element.scrollTop = element.scrollHeight
  }, [growth])

  return (
    <div
      ref={scroller}
      onScroll={(event) => {
        const element = event.currentTarget
        pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48
      }}
      className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-4 py-4"
    >
      {turns.map((turn) => (
        <Turn
          key={turn.key}
          turn={turn}
          onRetry={turn === last && !ask.streaming ? () => ask.retry(turn) : undefined}
          onSelectAsset={onSelectAsset}
          onFrame={onFrame}
        />
      ))}
    </div>
  )
}

function Turn({
  turn,
  onRetry,
  onSelectAsset,
  onFrame,
}: {
  turn: AskTurn
  onRetry?: () => void
  onSelectAsset: (assetId: string) => void
  onFrame: (bbox: [number, number, number, number]) => void
}) {
  const grouped = useMemo(
    () => groupReferences(turn.references, turn.text),
    [turn.references, turn.text],
  )
  const streaming = turn.status === 'streaming'

  return (
    <article className="flex flex-col gap-4">
      <p className="ml-auto max-w-[88%] whitespace-pre-wrap rounded-md border border-border bg-accent px-4 py-3 text-[15px]">
        {turn.prompt}
      </p>

      <div
        aria-busy={streaming}
        className="flex flex-col gap-4 border-l border-border pl-4 text-[15px] leading-relaxed"
      >
        <AnswerText
          text={turn.text}
          marks={grouped.marks}
          onSelect={onSelectAsset}
          trailing={streaming ? <Caret /> : null}
        />
        {turn.status === 'incomplete' ? (
          <div
            role="status"
            className="flex items-center gap-3 rounded-lg border border-border bg-background px-4 py-3"
          >
            <CircleAlert aria-hidden="true" className="size-5 shrink-0 text-muted-foreground" />
            <span className="flex-1">{turn.message}</span>
            {onRetry ? (
              <Button variant="outline" size="sm" onClick={onRetry}>
                Try again
              </Button>
            ) : null}
          </div>
        ) : null}
        <Citations grouped={grouped} onSelect={onSelectAsset} onFrame={onFrame} />
      </div>

      <OutputBox grouped={grouped} />
    </article>
  )
}

function Caret() {
  return (
    <span
      aria-hidden="true"
      className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.2em] animate-pulse bg-foreground"
    />
  )
}

/** The question box. Enter sends; Shift+Enter starts a new line. */
function Composer({
  ask,
  disabled,
  placeholder,
}: {
  ask: Ask
  disabled: boolean
  placeholder: string
}) {
  const box = useRef<HTMLTextAreaElement | null>(null)
  const { draft, setDraft, streaming } = ask
  const canSend = !disabled && !streaming && draft.trim() !== ''

  // A refused question comes back into the box: put the cursor in it, so the
  // next try is one key away.
  const previous = useRef(draft)
  useEffect(() => {
    if (previous.current === '' && draft !== '' && document.activeElement !== box.current) {
      box.current?.focus()
    }
    previous.current = draft
  }, [draft])

  function submit() {
    if (canSend) ask.send(draft)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-transparent bg-muted p-3 transition-colors focus-within:border-primary focus-within:ring-2 focus-within:ring-ring/30',
        disabled && 'opacity-60',
      )}
    >
      <textarea
        ref={box}
        aria-label="Question"
        rows={3}
        value={draft}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        className="w-full resize-none bg-transparent text-[15px] outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between">
        <span className={MICRO} aria-hidden="true">
          ⏎ to send
        </span>
        {streaming ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={ask.stop}
            className="border-transparent bg-background"
          >
            <Square aria-hidden="true" className="fill-current" />
            Stop
          </Button>
        ) : (
          <Button
            type="submit"
            variant="outline"
            size="sm"
            disabled={!canSend}
            className="border-transparent bg-background"
          >
            Send
          </Button>
        )}
      </div>
    </form>
  )
}

/** The user's sessions, newest first, each with its day and a delete. */
function SessionList({
  answer,
  failed,
  onRetry,
  currentId,
  now,
  onOpen,
  onDeleted,
}: {
  answer: chatSessionListResponse | undefined
  failed: boolean
  onRetry: () => void
  currentId: string
  now: number
  onOpen: (sessionId: string) => void
  onDeleted: (sessionId: string) => void
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const remove = useChatSessionDelete()

  function onDelete(session: ChatSession) {
    remove.mutate(
      { sessionId: session.session_id },
      {
        onSuccess: (answer) => {
          if (answer.status !== 204 && answer.status !== 404) {
            toast.show(`Couldn't delete the chat. The Ask service returned ${answer.status}.`)
            return
          }
          onDeleted(session.session_id)
          void queryClient.invalidateQueries({ queryKey: getChatSessionListQueryKey() })
        },
        onError: () => toast.show("Couldn't delete the chat. The portal did not answer."),
      },
    )
  }

  if (answer === undefined && !failed) {
    return (
      <div aria-label="Loading sessions" className="flex flex-col gap-3 p-4">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-4/5" />
        <Skeleton className="h-6 w-full" />
      </div>
    )
  }
  if (answer?.status === 503) {
    return <p className="p-4 text-sm text-muted-foreground">Ask is unavailable.</p>
  }
  if (failed || answer?.status !== 200) {
    return (
      <div className="flex items-center gap-3 p-4 text-sm text-muted-foreground">
        <span className="flex-1">Couldn't load your sessions.</span>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    )
  }

  const rows = answer.data.results
  if (rows.length === 0) {
    return <p className="p-4 text-[15px] text-muted-foreground">No sessions yet</p>
  }

  return (
    <ul className="min-h-0 flex-1 overflow-y-auto">
      {rows.map((session) => (
        <li
          key={session.session_id}
          className={cn(
            'flex items-center gap-3 border-b border-border px-4 py-3',
            session.session_id === currentId && 'bg-accent',
          )}
        >
          <button
            type="button"
            onClick={() => onOpen(session.session_id)}
            aria-current={session.session_id === currentId ? 'true' : undefined}
            className="min-w-0 flex-1 truncate text-left text-[15px] hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title={session.title}
          >
            {session.title || 'Untitled chat'}
          </button>
          <span className={cn(MICRO, 'shrink-0')}>{day(session.updated_at, now)}</span>
          <IconButton
            label={`Delete ${session.title || 'this chat'}`}
            onClick={() => onDelete(session)}
          >
            <Trash2 />
          </IconButton>
        </li>
      ))}
    </ul>
  )
}
