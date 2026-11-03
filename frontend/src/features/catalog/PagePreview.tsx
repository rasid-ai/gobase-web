import { useEffect, useState } from 'react'

import { getCatalogDocumentPageUrl } from '@/api/generated/catalog/catalog'
import { fetchWithSession } from '@/api/http-client'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

type Loaded = { key: string; url: string | null }

/** The page's mount: a hairline frame on the card, a sheet of paper inside. */
const FRAME = 'rounded-md border border-border bg-card p-1.5'

/**
 * One page of a document's PDF, rendered by the server with a passage's area
 * marked on it (docs/adr/020).
 *
 * Fetched rather than linked: an `<img src>` cannot carry the bearer token,
 * so the bytes come through the session and are shown as an object URL, the
 * way the PDF itself is opened (openDocument.ts). Mounted only once a passage
 * is expanded, so a page is never rendered for a row nobody opened.
 *
 * What was loaded is keyed by what was asked for, so a change of page is
 * "loading" by comparison rather than by a reset in the effect.
 */
export function PagePreview({
  assetId,
  name,
  page,
  chunkId,
}: {
  assetId: string
  /** The document's name, for the image's description. */
  name: string
  /** Counted from 1, as the passage reports it. */
  page: number
  chunkId: string
}) {
  const key = `${assetId}:${page}:${chunkId}`
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let url: string | null = null
    let cancelled = false

    fetchWithSession(getCatalogDocumentPageUrl(assetId, page, { chunk: chunkId }), {
      method: 'GET',
    })
      .then(async (response) => {
        if (response.status !== 200) throw new Error(`HTTP ${response.status}`)
        url = URL.createObjectURL(await response.blob())
        if (!cancelled) setLoaded({ key, url })
      })
      .catch(() => {
        if (!cancelled) setLoaded({ key, url: null })
      })

    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [assetId, page, chunkId, key])

  if (loaded === null || loaded.key !== key) {
    return (
      <div className={FRAME}>
        <Skeleton className="aspect-[1/1.3] w-full rounded-sm" aria-label="Loading page" />
      </div>
    )
  }
  if (loaded.url === null) {
    return (
      <p role="status" className={cn(FRAME, 'px-3 py-2.5 text-sm text-destructive')}>
        Could not render the page
      </p>
    )
  }
  return (
    <div className={FRAME}>
      <img
        src={loaded.url}
        alt={`Page ${page} of ${name}, passage highlighted`}
        className="block w-full rounded-sm"
      />
    </div>
  )
}
