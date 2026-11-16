import { useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useToast } from '@/components/ui/toast'

import { parseBbox, serializeBbox, type Bbox } from './bbox'

export type Area = { name: string | null; bbox: Bbox }

/**
 * The searched area, read from and written to the URL.
 *
 * `bbox` is the state and `place` is what to call it, so the pair travels
 * together: an area can be sent to a colleague and survives a reload
 * (docs/adr/011). `place` without `bbox` filters nothing and is dropped;
 * `bbox` without `place` is a hand-written link and still works, shown as the
 * box itself.
 *
 * A `bbox` that cannot be read is removed rather than ignored. Silently
 * widening someone's link from one city to the whole catalog looks like a
 * broken filter, so it says so once and shows everything.
 */
export function useAreaParam(): [Area | null, (area: Area | null) => void] {
  const [params, setParams] = useSearchParams()
  const toast = useToast()

  const raw = params.get('bbox')
  const bbox = parseBbox(raw)
  const unreadable = raw !== null && bbox === null

  const set = useCallback(
    (area: Area | null) => {
      const next = new URLSearchParams(params)
      if (area) {
        next.set('bbox', serializeBbox(area.bbox))
        if (area.name) next.set('place', area.name)
        else next.delete('place')
      } else {
        next.delete('bbox')
        next.delete('place')
      }
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  useEffect(() => {
    if (!unreadable) return
    toast.show("That link's area could not be read.")
    // Replace, so a reload does not fail again and Back does not land on it.
    // Removing the parameter is also what stops this firing twice.
    set(null)
  }, [unreadable, toast, set])

  if (bbox === null) return [null, set]
  return [{ name: params.get('place')?.slice(0, 200) ?? null, bbox }, set]
}
