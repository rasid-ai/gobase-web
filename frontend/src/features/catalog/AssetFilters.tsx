import { type LucideIcon, MapPin, TextSearch } from 'lucide-react'
import { type Ref, useRef } from 'react'

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
 * What the search box is searching (docs/adr/019). One at a time, chosen
 * before typing, so a word is never a name and a place at once. Semantic
 * search is the third, and is not built yet.
 */
export type SearchKind = 'metadata' | 'places'

const SEARCH_KINDS: { value: SearchKind; label: string; Icon: LucideIcon }[] = [
  { value: 'metadata', label: 'Metadata', Icon: TextSearch },
  { value: 'places', label: 'Places', Icon: MapPin },
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
  // The box is a different input for each kind, so choosing a kind hands
  // focus to the new one: choose, then type.
  const box = useRef<HTMLInputElement>(null)

  return (
    <aside
      aria-label="Filter assets"
      className="flex w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-border p-5"
    >
      <Segmented label="Browse by" value={mode} onChange={onMode} options={MODES} />

      <div className="flex flex-col gap-2">
        {searchKind === 'places' ? (
          <PlaceBox inputRef={box} query={placeQuery} onQuery={onPlaceQuery} onArea={onArea} />
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
            requestAnimationFrame(() => box.current?.focus())
          }}
        />

        {/*
          The filters the box set, each named by its kind, so a place and a
          search for the same word cannot be mistaken for each other. The
          metadata search is shown here only while the box is finding places;
          otherwise the box itself shows it.
        */}
        {searchKind === 'places' && search !== '' ? (
          <FilterChip
            kind="Metadata"
            value={search}
            removeLabel={`Remove metadata search ${search}`}
            onRemove={() => onSearch('')}
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
