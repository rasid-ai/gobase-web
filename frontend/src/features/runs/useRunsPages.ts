import { useInfiniteQuery } from '@tanstack/react-query'

import { getRunsListQueryKey, runsList } from '@/api/generated/runs/runs'

export const PAGE_SIZE = 25

/**
 * Paged runs.
 *
 * The generated hook fetches one page; the list needs to keep the pages it has
 * and ask for the next, so the generated request function is driven by an
 * infinite query instead. The cursor is the previous page's last run id.
 */
export function useRunsPages(statuses: readonly string[]) {
  const params = {
    limit: PAGE_SIZE,
    ...(statuses.length > 0 ? { status: statuses.join(',') } : {}),
  }

  return useInfiniteQuery({
    queryKey: getRunsListQueryKey(params),
    queryFn: ({ pageParam }) =>
      runsList({ ...params, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) =>
      last.status === 200 ? (last.data.next_cursor ?? undefined) : undefined,
  })
}
