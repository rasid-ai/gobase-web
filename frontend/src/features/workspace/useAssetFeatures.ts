import { useInfiniteQuery } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'

import { getMapAssetDataQueryKey, mapAssetData } from '@/api/generated/map/map'
import type { AssetDataFeaturesItem } from '@/api/generated/model'
import { serializeBbox } from '@/features/places/bbox'

import { serializeArea } from './drawnArea'
import { useLayers } from './layers'

/**
 * Features per request. The server caps this at `LAKE_PAGE_SIZE`, so the two
 * are raised together — a bigger number here alone is silently ignored.
 *
 * Large on purpose, and measured on the 1M-feature buildings layer over a
 * Beirut window. The scan is not where a page's time goes: it is ~12%, and
 * later pages do not re-read earlier row groups, because DuckDB skips every
 * row group before the cursor. The other ~88% is building each feature as
 * JSON, which costs the same per feature however it is paged. So a bigger
 * page mostly saves round trips — and on this side, re-sends: each page hands
 * MapLibre's worker the whole growing collection again, so three pages of
 * 10,000 send 60,000 features in all where five of 5,000 send 75,000.
 */
export const PAGE_SIZE = 10000

/**
 * How many pages one layer will pull for one window before it stops.
 *
 * A budget, not a cap on the data: zoom in and the next window is smaller, so
 * the same layer comes back whole. It exists because a window at world zoom
 * can hold a whole city's worth of features that no one can tell apart on
 * screen, and pulling all of them would cost a long wait for a smudge.
 *
 * Three pages of 10,000 — up to 30,000 features in a window. Roads over
 * greater Beirut (11,431) now fits in two, and buildings there (63,682) stops
 * at 30,000 and says so. At street and district zoom every layer finishes in
 * one page regardless, so this only bites zoomed out, where saying "zoom in
 * for the rest" is honest.
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
    // Never stale. Coming back to a window already read used to show the
    // cached features and then quietly download every page again, because
    // React Query treats data as stale at once by default. Nothing here can go
    // stale: an asset's content never changes under its id — changed content
    // gets a new asset_id (kb `content_hash`) — so a page read once is right
    // for as long as it is cached. gcTime is left at its default, so windows
    // you have left are dropped after five minutes and memory stays bounded.
    //
    // Across a reload the browser's own cache takes over: the server sends an
    // ETag and answers a matching one with an empty 304 (docs/adr/015).
    staleTime: Infinity,
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
