import { useState } from 'react'

import { openDocumentPdf } from './openDocument'

/**
 * Opens a document's PDF in a new tab. A button rather than a link because the
 * bytes need the session (see openDocument.ts). While they are fetched the
 * button waits; if they cannot be fetched it says so beside itself, in place,
 * and the button is there to try again.
 *
 * Used by the Assets page's cards and by the map's semantic results, so the
 * button's look is the caller's.
 */
export function OpenPdf({
  assetId,
  className,
  label = 'Open PDF',
}: {
  assetId: string
  className: string
  /** The button's text: "Open PDF" on a card, plain "Open" beside Draw in a row. */
  label?: string
}) {
  const [state, setState] = useState<'idle' | 'opening' | 'failed'>('idle')

  async function open() {
    setState('opening')
    const opened = await openDocumentPdf(assetId)
    setState(opened ? 'idle' : 'failed')
  }

  return (
    <>
      {state === 'failed' && (
        <span role="status" className="text-xs text-destructive">
          Could not open the PDF
        </span>
      )}
      <button type="button" onClick={open} disabled={state === 'opening'} className={className}>
        {label}
      </button>
    </>
  )
}
