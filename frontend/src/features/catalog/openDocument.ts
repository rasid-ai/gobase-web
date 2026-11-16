import { getCatalogDocumentPdfUrl } from '@/api/generated/catalog/catalog'
import { fetchWithSession } from '@/api/http-client'

/**
 * Open a document's PDF in a new tab.
 *
 * Not a link: the PDF endpoint needs the bearer token, which a plain `href`
 * cannot carry (docs/adr/027). So the tab is opened first — synchronously,
 * inside the click, which is what popup blockers allow — and then pointed at
 * the bytes once they have been fetched with the session and wrapped in an
 * object URL. The blob keeps `application/pdf`, so the browser's own viewer
 * shows it.
 *
 * Resolves to false when the PDF could not be fetched, and closes the tab
 * again so nothing is left blank. The object URL is kept for the life of the
 * page: the tab may reload it, and nothing says when the tab is closed.
 *
 * `page` opens the viewer at that page, counted from 1 as the passages
 * endpoint reports it: every browser's viewer honours `#page=N` on the URL
 * (docs/adr/027, docs/adr/020).
 */
export async function openDocumentPdf(assetId: string, page?: number): Promise<boolean> {
  const tab = window.open('', '_blank')
  if (!tab) return false

  try {
    const response = await fetchWithSession(getCatalogDocumentPdfUrl(assetId), { method: 'GET' })
    if (response.status !== 200) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    tab.location.href = URL.createObjectURL(blob) + (page ? `#page=${page}` : '')
    return true
  } catch {
    tab.close()
    return false
  }
}
