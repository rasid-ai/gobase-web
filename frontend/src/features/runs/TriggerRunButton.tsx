import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { getRunsListQueryKey, useRunsTrigger } from '@/api/generated/runs/runs'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'

export type TriggerOutcome = { tone: 'ok' | 'warn' | 'error'; message: string }

/**
 * Admin-only launch, always behind a confirm dialog (context/ui-rules.md).
 * Dismissing the dialog launches nothing.
 *
 * The button is also disabled while a run is in flight, mirroring the server's
 * own refusal — the server is the real guard, this only avoids a pointless
 * round trip and a confusing 409.
 */
export function TriggerRunButton({
  disabled,
  onOutcome,
}: {
  disabled: boolean
  onOutcome: (outcome: TriggerOutcome) => void
}) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const trigger = useRunsTrigger()

  const launch = () => {
    trigger.mutate(undefined, {
      // The HTTP client returns non-2xx rather than throwing, so every
      // outcome arrives here and is told apart by its status.
      onSuccess: (response) => {
        setOpen(false)
        if (response.status === 202) {
          onOutcome({ tone: 'ok', message: `Run ${response.data.id.slice(0, 8)} started.` })
          void queryClient.invalidateQueries({ queryKey: getRunsListQueryKey() })
          return
        }
        if (response.status === 409) {
          onOutcome({ tone: 'warn', message: 'A run is already in progress.' })
          void queryClient.invalidateQueries({ queryKey: getRunsListQueryKey() })
          return
        }
        onOutcome({
          tone: 'error',
          message:
            response.status === 503
              ? 'Dagster is unreachable, so nothing was started.'
              : 'Dagster refused to start the run.',
        })
      },
      onError: () => {
        setOpen(false)
        onOutcome({ tone: 'error', message: 'The request to start a run did not complete.' })
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" disabled={disabled} onClick={() => setOpen(true)}>
        Run pipeline
      </Button>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Start the ingestion pipeline now?</DialogTitle>
        <DialogDescription>
          This runs the full weekly pipeline once, outside its schedule. It cannot be stopped from
          the portal.
        </DialogDescription>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm" disabled={trigger.isPending}>
              Cancel
            </Button>
          </DialogClose>
          <Button size="sm" onClick={launch} disabled={trigger.isPending}>
            {trigger.isPending ? 'Starting…' : 'Start run'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
