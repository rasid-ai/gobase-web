import { useState } from 'react'

import { usePlacesSearch } from '@/api/generated/places/places'
import type { Place } from '@/api/generated/model'

import { useDebounced } from './useDebounced'

/** Below this, a search is too vague to be worth asking for — or paying for. */
export const MIN_QUERY = 3

export type PlaceSearchState =
  | { status: 'idle'; places: readonly Place[] }
  | { status: 'loading'; places: readonly Place[] }
  | { status: 'ready'; places: readonly Place[] }
  | { status: 'empty'; places: readonly Place[] }
  | { status: 'error'; places: readonly Place[] }
  | { status: 'unavailable'; places: readonly Place[] }

/**
 * Places matching what has been typed, once typing has paused.
 *
 * `skip` is how the coordinate path stays free: text that looks like a
 * coordinate pair never reaches the geocoder at all.
 *
 * A 503 latches. It means the geocoder is switched off or unconfigured, which
 * will not change between two keystrokes, so it is asked once a session rather
 * than once a character.
 */
export function usePlaceSearch(text: string, { skip = false }: { skip?: boolean } = {}) {
  const settled = useDebounced(text.trim())
  const [unavailable, setUnavailable] = useState(false)

  const enabled = !skip && !unavailable && settled.length >= MIN_QUERY
  const query = usePlacesSearch(
    { q: settled },
    { query: { enabled, retry: false, staleTime: 5 * 60 * 1000 } },
  )

  // State rather than a ref, and set during render rather than in an effect:
  // the latch has to be visible to the very render that decides whether to ask
  // again, and a ref would not be.
  if (!unavailable && query.data?.status === 503) setUnavailable(true)

  return { ...state(), typing: !skip && text.trim() !== settled }

  function state(): PlaceSearchState {
    const none: readonly Place[] = []
    if (unavailable) return { status: 'unavailable', places: none }
    if (!enabled) return { status: 'idle', places: none }
    if (query.isPending || query.isFetching) return { status: 'loading', places: none }
    if (query.isError || query.data?.status !== 200) return { status: 'error', places: none }

    const places = query.data.data.results
    return places.length === 0 ? { status: 'empty', places: none } : { status: 'ready', places }
  }
}
