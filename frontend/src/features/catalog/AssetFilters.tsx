import type { DataTypeCount, Place } from '@/api/generated/model'
import { Button } from '@/components/ui/button'
import { ComboboxPopup } from '@/components/ui/combobox'
import { Input } from '@/components/ui/input'
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

export function AssetFilters({
  search,
  onSearch,
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
  search: string
  onSearch: (next: string) => void
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
  return (
    <aside
      aria-label="Filter assets"
      className="flex w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-border p-5"
    >
      <SearchBox search={search} onSearch={onSearch} onArea={onArea} />

      {/*
        The area sits under the box that set it, and is removed from there.
        With no place name — a hand-written link — the box itself is the label,
        and a coordinate box is data chrome, so it is mono.
      */}
      {area ? (
        <div className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5">
          <span
            className={cn('min-w-0 flex-1 truncate text-sm', !area.name && 'font-mono text-[11px]')}
            title={area.name ?? formatBbox(area.bbox) ?? undefined}
          >
            {area.name ?? formatBbox(area.bbox)}
          </span>
          <button
            type="button"
            onClick={() => onArea(null)}
            aria-label={`Remove area ${area.name ?? 'filter'}`}
            className="rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            ✕
          </button>
        </div>
      ) : null}

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
 * The rail's search box: asset names and places at once.
 *
 * Typing filters the grid by name straight away, exactly as it did before, and
 * the same text is offered to the geocoder underneath. Both answers are
 * available and you pick — which is how "Beirut" stops being ambiguous without
 * anyone having to guess which of the two was meant.
 */
function SearchBox({
  search,
  onSearch,
  onArea,
}: {
  search: string
  onSearch: (next: string) => void
  onArea: (area: Area | null) => void
}) {
  const places = usePlaceSearch(search)

  const combobox = useCombobox({
    count: places.places.length,
    hasPopup: hasPlaceOptions(places),
    onSelect: (index) => pick(places.places[index]),
  })

  function pick(place: Place) {
    // The name filter is left alone on purpose: the two combine, so an area
    // plus a name is a question you can ask.
    if (place.bbox) onArea({ name: place.name, bbox: place.bbox as Area['bbox'] })
  }

  return (
    <div {...combobox.rootProps} className="relative">
      <Input
        type="search"
        value={search}
        onChange={(event) => {
          onSearch(event.target.value)
          combobox.reopen()
        }}
        placeholder="Search names or places…"
        aria-label="Search asset names"
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
