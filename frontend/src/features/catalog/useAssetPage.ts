import { keepPreviousData } from '@tanstack/react-query'

import { useCatalogAssetList } from '@/api/generated/catalog/catalog'
import type { CatalogAssetListParams } from '@/api/generated/model'

export const PAGE_SIZE = 12

/**
 * One page of the catalog.
 *
 * Paging is by offset rather than by cursor because the list sorts by several
 * columns and says how many assets match in total; a cursor over one id serves
 * neither (docs/adr/010).
 *
 * The page you were on stays up until the next one answers, so stepping
 * through the catalog does not drop the grid to skeletons and back on every
 * click.
 */
export function useAssetPage(filters: CatalogAssetListParams, page: number) {
  return useCatalogAssetList(
    { ...filters, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE },
    { query: { placeholderData: keepPreviousData } },
  )
}
