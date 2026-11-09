import { MessageSquare } from 'lucide-react'

/** The button that opens the panel, with a dot when an answer ended unseen. */
export function AskToggle({ unread, onOpen }: { unread: boolean; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={unread ? 'Open Ask, an answer is ready' : 'Open Ask'}
      className="pointer-events-auto relative inline-flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-2 font-mono text-[12px] uppercase tracking-[0.06em] backdrop-blur transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <MessageSquare aria-hidden="true" className="size-4" />
      Ask
      {unread ? (
        <span
          aria-hidden="true"
          className="absolute -right-1 -top-1 size-2.5 rounded-full bg-primary ring-2 ring-background"
        />
      ) : null}
    </button>
  )
}
