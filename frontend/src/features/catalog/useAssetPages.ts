import { useInfiniteQuery } from '@tanstack/react-query'

import { catalogAssetList, getCatalogAssetListQueryKey } from '@/api/generated/catalog/catalog'
import type { CatalogAssetListParams } from '@/api/generated/model'

export const PAGE_SIZE = 24

/**
 * Paged catalog assets.
 *
 * The generated hook fetches one page; the list keeps the pages it has and
 * asks for the next, so the generated request function is driven by an
 * infinite query instead — the same shape the Runs page uses.
 *
 * Paging is by offset rather than by cursor because the list sorts by several
 * columns and reports how many assets match in total; a cursor over one id
 * serves neither.
 */
export function useAssetPages(filters: CatalogAssetListParams) {
  const params = { ...filters, limit: PAGE_SIZE }

  return useInfiniteQuery({
    queryKey: getCatalogAssetListQueryKey(params),
    queryFn: ({ pageParam }) => catalogAssetList({ ...params, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      if (last.status !== 200) return undefined
      const loaded = pages.reduce(
        (total, page) => total + (page.status === 200 ? page.data.results.length : 0),
        0,
      )
      return loaded < last.data.count ? loaded : undefined
    },
  })
}
