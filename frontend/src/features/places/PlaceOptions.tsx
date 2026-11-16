import {
  ComboboxLabel,
  ComboboxList,
  ComboboxOption,
  ComboboxStatus,
} from '@/components/ui/combobox'

import type { PlaceSearchState } from './usePlaceSearch'

/**
 * What a place search shows under the box, in every state it can be in.
 *
 * Each row is two lines, and that split is the mono rule made visible: the
 * place's name is body text, because a name is not data chrome; its coordinate
 * underneath is mono, because a coordinate is (context/design-system.md).
 */
export function PlaceOptions({
  state,
  listId,
  optionProps,
  activeIndex,
}: {
  state: PlaceSearchState
  listId: string
  optionProps: (index: number) => Record<string, unknown>
  activeIndex: number | null
}) {
  if (state.status === 'ready') {
    return (
      <>
        <ComboboxLabel>Places</ComboboxLabel>
        <ComboboxList id={listId} label="Places">
          {state.places.map((place, index) => (
            <ComboboxOption
              key={place.name + index}
              active={index === activeIndex}
              {...optionProps(index)}
            >
              <span className="block text-sm leading-snug">{place.name}</span>
              <span className="block font-mono text-[11px] text-muted-foreground">
                {place.lat.toFixed(4)}, {place.lon.toFixed(4)}
              </span>
            </ComboboxOption>
          ))}
        </ComboboxList>
      </>
    )
  }

  return <ComboboxStatus>{MESSAGE[state.status]}</ComboboxStatus>
}

const MESSAGE: Record<Exclude<PlaceSearchState['status'], 'ready'>, string> = {
  idle: '',
  loading: 'Searching…',
  empty: 'No place found.',
  error: 'Address search failed. Try again.',
  unavailable: 'Address search is unavailable.',
}

/** Whether there is anything at all to show for this state. */
export function hasPlaceOptions(state: PlaceSearchState): boolean {
  return state.status !== 'idle'
}
