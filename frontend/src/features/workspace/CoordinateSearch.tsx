import { useId, useState } from 'react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

import { type Coordinates, parseCoordinates } from './coordinates'

/**
 * Go to a coordinate.
 *
 * One box rather than two, because the ordinary case is pasting a pair copied
 * from a mapping site and two fields would mean splitting it by hand first.
 * Latitude first, matching what gets pasted (specs/map.md).
 *
 * Nothing moves until the input is valid: a bad coordinate is a form error
 * shown in place, not a failed trip somewhere.
 */
export function CoordinateSearch({ onGo }: { onGo: (coordinates: Coordinates) => void }) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputId = useId()
  const errorId = useId()

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const result = parseCoordinates(text)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    onGo(result.value)
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Go to coordinates"
      className="flex w-[18rem] flex-col gap-2 rounded-md border border-border bg-background/95 p-2 backdrop-blur"
    >
      <label
        htmlFor={inputId}
        className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
      >
        Latitude, longitude
      </label>

      <div className="flex gap-2">
        <Input
          id={inputId}
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            // Clear the error as soon as the input changes: keeping it while
            // someone is fixing the value reads as if the fix did not register.
            if (error) setError(null)
          }}
          placeholder="51.0504, 13.7373"
          inputMode="text"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className="h-8"
        />
        <Button type="submit" size="sm" variant="outline" disabled={text.trim() === ''}>
          Go
        </Button>
      </div>

      {error ? (
        <Alert id={errorId} className="px-2 py-1 text-[12px]">
          {error}
        </Alert>
      ) : null}
    </form>
  )
}
