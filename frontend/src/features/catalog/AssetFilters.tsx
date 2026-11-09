import { CornerDownLeft, type LucideIcon, MapPin, Sparkles, TextSearch } from 'lucide-react'
import {
  type FormEvent,
  type KeyboardEvent,
  type Ref,
  type RefCallback,
  useCallback,
  useRef,
  useState,
} from 'react'

import type { DataTypeCount, Place } from '@/api/generated/model'
import { Button } from '@/components/ui/button'
import { ComboboxPopup } from '@/components/ui/combobox'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { useCombobox } from '@/components/ui/useCombobox'
import { hasPlaceOptions, PlaceOptions } from '@/features/places/PlaceOptions'
import type { Area } from '@/features/places/useAreaParam'
import { usePlaceSearch } from '@/features/places/usePlaceSearch'
import { formatBbox } from '@/features/catalog/formatAsset'
import { cn } from '@/lib/utils'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/**
 * How far back to look, in days. `null` is any time.
 *
 * These are portal choices, unlike the data types beside them — a window is
 * not something the knowledge base defines.
 */
export const INGESTION_WINDOWS: { key: string; label: string; days: number | null }[] = [
  { key: 'any', label: 'Any time', days: null },
  { key: '7', label: 'Last 7 days', days: 7 },
  { key: '30', label: 'Last 30 days', days: 30 },
  { key: '90', label: 'Last 90 days', days: 90 },
]

/** The moment a window starts, or undefined when it does not start. */
export function ingestedAfter(windowKey: string, now: Date = new Date()): string | undefined {
  const days = INGESTION_WINDOWS.find((option) => option.key === windowKey)?.days
  if (!days) return undefined
  return new Date(now.getTime() - days * 86_400_000).toISOString()
}

/**
 * A chosen window, and the moment it starts.
 *
 * The moment is fixed when the window is chosen, not worked out on every
 * render: a fresh `new Date()` per render made a new query key per render, and
 * every answer asked again, without end.
 */
export type IngestionWindow = { key: string; after: string | undefined }

export const ANY_TIME: IngestionWindow = { key: 'any', after: undefined }

/**
 * The two ways to browse (docs/adr/016): datasets first and then their files,
 * or every asset at once.
 */
export type BrowseMode = 'datasets' | 'assets'

const MODES: { value: BrowseMode; label: string }[] = [
  { value: 'datasets', label: 'Datasets' },
  { value: 'assets', label: 'Assets' },
]

/**
 * What the search box is searching (docs/adr/019, docs/adr/020). One at a
 * time, chosen before typing, so a word is never a name and a place at once.
 * Semantic finds passages by meaning, and is asked on submit rather than as
 * typed: an embedding per keystroke is the wrong shape.
 */
export type SearchKind = 'metadata' | 'places' | 'semantic'

const SEARCH_KINDS: { value: SearchKind; label: string; Icon: LucideIcon }[] = [
  { value: 'metadata', label: 'Metadata', Icon: TextSearch },
  { value: 'places', label: 'Places', Icon: MapPin },
  { value: 'semantic', label: 'Semantic', Icon: Sparkles },
]

export function AssetFilters({
  mode,
  onMode,
  searchKind,
  onSearchKind,
  search,
  onSearch,
  searchLabel,
  placeholder,
  placeQuery,
  onPlaceQuery,
  question,
  onAsk,
  dataTypes,
  selectedTypes,
  onToggleType,
  window: windowKey,
  onWindow,
  area,
  onArea,
  onClear,
  dirty,
}: {
  mode: BrowseMode
  onMode: (next: BrowseMode) => void
  searchKind: SearchKind
  onSearchKind: (next: SearchKind) => void
  /** The metadata search: a filter, applied as it is typed. */
  search: string
  onSearch: (next: string) => void
  /** What the metadata search searches, for assistive technology: it changes with the level. */
  searchLabel: string
  placeholder: string
  /** What is typed to find a place. Not a filter: picking a place is. */
  placeQuery: string
  onPlaceQuery: (next: string) => void
  /** The question asked, once submitted. Empty is none. */
  question: string
  onAsk: (question: string) => void
  /** Straight from the API — the portal never holds its own list of data types. */
  dataTypes: readonly DataTypeCount[]
  selectedTypes: readonly string[]
  onToggleType: (dataType: string) => void
  window: string
  onWindow: (next: string) => void
  area: Area | null
  onArea: (area: Area | null) => void
  onClear: () => void
  dirty: boolean
}) {
  // The box is a different field for each kind — a textarea for a question,
  // an input otherwise — so choosing a kind hands focus to the new one:
  // choose, then type. A callback ref, since one object ref cannot be typed
  // for both.
  const field = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
  const box = useCallback((element: HTMLInputElement | HTMLTextAreaElement | null) => {
    field.current = element
  }, [])

  return (
    <aside
      aria-label="Filter assets"
      className="flex w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-border p-5"
    >
      <Segmented label="Browse by" value={mode} onChange={onMode} options={MODES} />

      <div className="flex flex-col gap-2">
        {searchKind === 'places' ? (
          <PlaceBox inputRef={box} query={placeQuery} onQuery={onPlaceQuery} onArea={onArea} />
        ) : searchKind === 'semantic' ? (
          <QuestionBox inputRef={box} question={question} onAsk={onAsk} />
        ) : (
          <Input
            ref={box}
            type="search"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder={placeholder}
            aria-label={searchLabel}
          />
        )}

        <SearchKindSwitch
          value={searchKind}
          onChange={(next) => {
            onSearchKind(next)
            requestAnimationFrame(() => field.current?.focus())
          }}
        />

        {/*
          The filters the box set, each named by its kind, so a place and a
          search for the same word cannot be mistaken for each other. The
          metadata search is shown here only while the box is finding places;
          otherwise the box itself shows it.
        */}
        {searchKind !== 'metadata' && search !== '' ? (
          <FilterChip
            kind="Metadata"
            value={search}
            removeLabel={`Remove metadata search ${search}`}
            onRemove={() => onSearch('')}
          />
        ) : null}
        {/*
          The question is a filter from the moment it is asked, so its chip is
          shown in every kind: the box holds a draft, the chip what was asked.
        */}
        {question !== '' ? (
          <FilterChip
            kind="Semantic"
            value={question}
            removeLabel="Remove question"
            onRemove={() => onAsk('')}
          />
        ) : null}
        {/*
          With no place name — a hand-written link — the box itself is the
          label, and a coordinate box is data chrome, so it is mono.
        */}
        {area ? (
          <FilterChip
            kind="Place"
            value={area.name ?? formatBbox(area.bbox) ?? ''}
            mono={!area.name}
            removeLabel={`Remove area ${area.name ?? 'filter'}`}
            onRemove={() => onArea(null)}
          />
        ) : null}
      </div>

      {/*
        The data types are whatever the catalog returned, with the counts it
        reported. The portal neither defines nor orders that list
        (context/integrations/kb.md), so an empty answer renders no group at
        all rather than an empty one.
      */}
      {dataTypes.length > 0 && (
        <div role="group" aria-label="Filter by data type">
          <p className={MICRO}>Data type</p>
          <ul className="mt-2 flex flex-col">
            {dataTypes.map((type) => (
              <li key={type.data_type}>
                <CheckRow
                  label={type.data_type}
                  count={type.count}
                  checked={selectedTypes.includes(type.data_type)}
                  onClick={() => onToggleType(type.data_type)}
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      <div role="radiogroup" aria-label="Filter by date of ingestion">
        <p className={MICRO}>Date of ingestion</p>
        <ul className="mt-2 flex flex-col">
          {INGESTION_WINDOWS.map((option) => (
            <li key={option.key}>
              <button
                type="button"
                role="radio"
                aria-checked={windowKey === option.key}
                onClick={() => onWindow(option.key)}
                className="flex w-full items-center gap-2.5 py-1 text-left"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    'size-3 shrink-0 rounded-full border',
                    windowKey === option.key
                      ? 'border-primary bg-primary'
                      : 'border-border bg-transparent',
                  )}
                />
                <span
                  className={cn(
                    'text-sm',
                    windowKey === option.key
                      ? 'font-medium text-foreground'
                      : 'text-muted-foreground',
                  )}
                >
                  {option.label}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* Only offered once there is something to clear. */}
      {dirty && (
        <Button variant="ghost" size="sm" className="self-start px-0" onClick={onClear}>
          Clear all filters
        </Button>
      )}
    </aside>
  )
}

function CheckRow({
  label,
  count,
  checked,
  onClick,
}: {
  label: string
  count: number
  checked: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={onClick}
      className="flex w-full items-center gap-2.5 py-1 text-left"
    >
      <span
        aria-hidden="true"
        className={cn(
          'flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border text-[9px] leading-none',
          checked
            ? 'border-primary bg-primary text-primary-foreground'
            : 'border-border bg-transparent',
        )}
      >
        {checked ? '✓' : ''}
      </span>
      <span className={cn('flex-1 text-sm', checked ? 'font-medium' : 'text-muted-foreground')}>
        {label}
      </span>
      <span className="font-mono text-[11px] text-muted-foreground">{count}</span>
    </button>
  )
}

/**
 * What the search box searches: small icons under it.
 *
 * Quieter than the Datasets / Assets switch on purpose. That one changes what
 * the page lists; this one changes only what the box is for. Each icon's name
 * is its tooltip and what assistive technology reads.
 */
function SearchKindSwitch({
  value,
  onChange,
}: {
  value: SearchKind
  onChange: (next: SearchKind) => void
}) {
  return (
    <div role="radiogroup" aria-label="Search by" className="flex items-center gap-1">
      {SEARCH_KINDS.map(({ value: kind, label, Icon }) => (
        <button
          key={kind}
          type="button"
          role="radio"
          aria-checked={value === kind}
          aria-label={label}
          title={`Search ${label.toLowerCase()}`}
          onClick={() => onChange(kind)}
          className={cn(
            'flex size-7 items-center justify-center rounded-md',
            'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
            value === kind
              ? 'bg-primary/15 text-primary'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <Icon aria-hidden className="size-4" />
        </button>
      ))}
    </div>
  )
}

/**
 * The search box while it asks by meaning: three lines of question, and under
 * them, inside the same border, how to send it and the button that does.
 *
 * Sent on Enter or the button, never as typed, the way the map's Semantic
 * pane does it (docs/adr/018): every submission is an embedding round trip.
 * Shift+Enter breaks a line, since a question can be longer than a word. The
 * box holds a draft seeded from the question asked; the chip under it shows
 * what is actually applied.
 */
function QuestionBox({
  inputRef,
  question,
  onAsk,
}: {
  inputRef: RefCallback<HTMLTextAreaElement>
  question: string
  onAsk: (question: string) => void
}) {
  const [draft, setDraft] = useState(question)
  // The draft follows the question when it changes from outside — asked,
  // removed, or cleared with everything else — without a remount, so the
  // box keeps its focus. Set during render, not in an effect.
  const [seed, setSeed] = useState(question)
  if (seed !== question) {
    setSeed(question)
    setDraft(question)
  }

  function submit(event?: FormEvent) {
    event?.preventDefault()
    const asked = draft.trim()
    if (asked !== '') onAsk(asked)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Search by meaning"
      className={cn(
        'flex flex-col rounded-md border border-border bg-input',
        'focus-within:border-ring focus-within:ring-2 focus-within:ring-ring',
      )}
    >
      <textarea
        ref={inputRef}
        rows={3}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Describe what you are looking for…"
        aria-label="Ask about documents"
        maxLength={500}
        className="w-full resize-none bg-transparent px-3 py-2 text-sm leading-snug placeholder:text-muted-foreground focus-visible:outline-none"
      />
      <div className="flex items-center justify-between gap-2 px-2 pb-2 pl-3">
        <span className={cn(MICRO, 'flex items-center gap-1')}>
          <CornerDownLeft aria-hidden className="size-3" />
          to search
        </span>
        <Button type="submit" variant="outline" size="sm" disabled={draft.trim() === ''}>
          Search
        </Button>
      </div>
    </form>
  )
}

/** A filter the search box set, named by its kind, and the way to remove it. */
function FilterChip({
  kind,
  value,
  mono = false,
  removeLabel,
  onRemove,
}: {
  kind: string
  value: string
  mono?: boolean
  removeLabel: string
  onRemove: () => void
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5">
      <span className={MICRO}>{kind}</span>
      <span
        className={cn('min-w-0 flex-1 truncate text-sm', mono && 'font-mono text-[11px]')}
        title={value}
      >
        {value}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={removeLabel}
        className="rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        ✕
      </button>
    </div>
  )
}

/**
 * The search box while it finds places.
 *
 * What is typed goes to the geocoder and nowhere else: it filters nothing
 * until a place is picked, and a metadata search is never billed as a place
 * search (docs/adr/011). Picking sets the area and empties the box; the
 * area's chip names it from then on, and the metadata search is left alone,
 * so the two combine.
 */
function PlaceBox({
  inputRef,
  query,
  onQuery,
  onArea,
}: {
  inputRef: Ref<HTMLInputElement>
  query: string
  onQuery: (next: string) => void
  onArea: (area: Area | null) => void
}) {
  const places = usePlaceSearch(query)

  const combobox = useCombobox({
    count: places.places.length,
    hasPopup: hasPlaceOptions(places),
    onSelect: (index) => pick(places.places[index]),
  })

  function pick(place: Place) {
    if (!place.bbox) return
    onArea({ name: place.name, bbox: place.bbox as Area['bbox'] })
    onQuery('')
  }

  return (
    <div {...combobox.rootProps} className="relative">
      <Input
        ref={inputRef}
        type="search"
        value={query}
        onChange={(event) => {
          onQuery(event.target.value)
          combobox.reopen()
        }}
        placeholder="Place name…"
        aria-label="Search places"
        {...combobox.inputProps}
      />

      {combobox.open ? (
        <ComboboxPopup>
          <PlaceOptions
            state={places}
            listId={combobox.listId}
            optionProps={combobox.optionProps}
            activeIndex={combobox.activeIndex}
          />
        </ComboboxPopup>
      ) : null}
    </div>
  )
}
