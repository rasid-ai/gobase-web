import { useState } from 'react'

import { openDocumentPdf } from './openDocument'

/**
 * Opens a document's PDF in a new tab. A button rather than a link because the
 * bytes need the session (see openDocument.ts). While they are fetched the
 * button waits; if they cannot be fetched it says so beside itself, in place,
 * and the button is there to try again.
 *
 * The caller passes the classes, so the button looks like whatever surrounds it.
 */
export function OpenPdf({ assetId, className }: { assetId: string; className: string }) {
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
        Open PDF
      </button>
    </>
  )
}
