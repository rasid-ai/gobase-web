import { useInfiniteQuery } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'

import { getMapAssetDataQueryKey, mapAssetData } from '@/api/generated/map/map'
import type { AssetDataFeaturesItem } from '@/api/generated/model'
import { serializeBbox } from '@/features/places/bbox'

import { serializeArea } from './drawnArea'
import { useLayers } from './layers'

/**
 * Features per request. The server caps this at its own page size.
 *
 * Large on purpose. Every request re-opens the file — DuckDB keeps no result
 * between calls — so a page is a round trip, and a big page makes one request
 * the normal case. The scan itself is cheap and does not grow with the page
 * number: the cursor is a range filter, so DuckDB stops as soon as it has
 * enough rows rather than reading the file and skipping.
 */
export const PAGE_SIZE = 5000

/**
 * How many pages one layer will pull for one window before it stops.
 *
 * A budget, not a cap on the data: zoom in and the next window is smaller, so
 * the same layer comes back whole. It exists because a window at world zoom
 * can hold a whole city's worth of features that no one can tell apart on
 * screen, and pulling all of them would cost a long wait for a smudge.
 *
 * Three, because two stopped just short of finishing real layers. Measured
 * against silver after the covering column landed (docs/adr/013): roads over
 * greater Beirut holds 11,431 features and takes three pages — 149ms, 184ms,
 * 66ms — so a budget of two showed 10,000 of them and asked the user to zoom
 * in, for the sake of a third page costing 66ms. At street and district zoom
 * every layer finishes in one page regardless, so this only bites zoomed out,
 * where saying "zoom in for the rest" is honest.
 */
export const PAGE_BUDGET = 3

export type AssetFeatures = {
  features: readonly AssetDataFeaturesItem[]
  count: number
  /** The budget stopped the read before the window was exhausted. */
  truncated: boolean
  loading: boolean
  failed: boolean
  /** The asset has no vector data at all, which is a different thing to say. */
  notFound: boolean
  /**
   * What the read was scoped to. It decides how a truncated layer is
   * explained: zooming in shrinks a window, but does nothing to a drawn area.
   */
  scope: 'view' | 'area'
}

/**
 * One asset's features for the drawn area if there is one, else the window.
 *
 * The generated hook fetches a single page; a layer needs to keep the pages it
 * has and ask for the next, so the generated request function is driven by an
 * infinite query instead — the same shape `useRunsPages` uses. The cursor is
 * the previous page's last row in the file.
 *
 * Reads the scope from the layers context itself rather than taking it as an
 * argument. The map, the asset row and the layers panel all call this for the
 * same asset, and one request serves all three only if all three build the
 * same query key — which is guaranteed when none of them can pass a different
 * scope.
 *
 * Keyed on the scope, so panning back to a window already read, or redrawing
 * nothing, is a cache hit rather than another trip to the lake.
 */
export function useAssetFeatures(assetId: string, enabled: boolean): AssetFeatures {
  const { view, drawnArea } = useLayers()
  const scope = drawnArea ? 'area' : 'view'
  // Order matters: the generated client builds the query string in this
  // object's own order, and the tests key on the whole URL.
  const params = {
    limit: PAGE_SIZE,
    ...(drawnArea ? { area: serializeArea(drawnArea) } : view ? { bbox: serializeBbox(view) } : {}),
  }

  const query = useInfiniteQuery({
    queryKey: getMapAssetDataQueryKey(assetId, params),
    queryFn: ({ pageParam }) =>
      mapAssetData(assetId, {
        ...params,
        ...(pageParam === undefined ? {} : { cursor: pageParam }),
      }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) =>
      last.status === 200 ? (last.data.next_cursor ?? undefined) : undefined,
    // A drawn area needs no window. A window-scoped read waits for the map to
    // report one, rather than asking for the whole file in the meantime.
    enabled: enabled && (drawnArea !== null || view !== null),
  })

  const pages = query.data?.pages
  const loaded = pages?.length ?? 0
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = query

  // Walk the window until it is read or the budget runs out. An effect rather
  // than a loop in the query: each page has to come back before the next one
  // can be asked for, since its cursor is what asks.
  useEffect(() => {
    if (!hasNextPage || isFetchingNextPage || loaded >= PAGE_BUDGET) return
    void fetchNextPage()
  }, [hasNextPage, isFetchingNextPage, loaded, fetchNextPage])

  const features = useMemo(
    () => (pages ?? []).flatMap((page) => (page.status === 200 ? page.data.features : [])),
    [pages],
  )

  // A page that answered with anything but 200 is a failure the panel shows;
  // `isError` alone would miss it, because the client returns the status
  // rather than throwing it.
  const refused = (pages ?? []).find((page) => page.status !== 200)

  return {
    features,
    count: features.length,
    truncated: loaded >= PAGE_BUDGET && Boolean(hasNextPage),
    loading: query.isFetching,
    failed: query.isError || refused !== undefined,
    notFound: refused?.status === 404,
    scope,
  }
}
