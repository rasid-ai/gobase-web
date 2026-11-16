import { useId, useState } from 'react'

import type { Place } from '@/api/generated/model'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ComboboxPopup } from '@/components/ui/combobox'
import { Input } from '@/components/ui/input'
import { useCombobox } from '@/components/ui/useCombobox'
import { hasPlaceOptions, PlaceOptions } from '@/features/places/PlaceOptions'
import { usePlaceSearch } from '@/features/places/usePlaceSearch'

import { type Coordinates, looksLikeCoordinates, parseCoordinates } from './coordinates'

/**
 * Go to a place, or to a coordinate.
 *
 * One box for both, because they answer the same question and asking which
 * kind of answer you have before you type it is work the box can do itself.
 * What is typed decides: two numbers are a coordinate and never reach the
 * geocoder; anything else is an address and offers candidates underneath.
 *
 * The coordinate path is unchanged. One box rather than two, latitude first,
 * matching what gets pasted; nothing moves until the input is valid, and a bad
 * coordinate is a form error shown in place (specs/map.md).
 */
export function PlaceSearch({
  onGo,
  onGoPlace,
}: {
  onGo: (coordinates: Coordinates) => void
  onGoPlace: (place: Place) => void
}) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputId = useId()
  const errorId = useId()

  const coordinate = looksLikeCoordinates(text)
  const search = usePlaceSearch(text, { skip: coordinate })

  const combobox = useCombobox({
    count: search.places.length,
    hasPopup: hasPlaceOptions(search),
    onSelect: (index) => {
      setError(null)
      setText(search.places[index].name)
      onGoPlace(search.places[index])
    },
    onSubmit: submit,
  })

  function submit() {
    if (!coordinate) {
      // Never guess a candidate, even when there is only one: picking is an
      // explicit act, and going somewhere nobody chose is worse than waiting.
      if (search.status === 'empty') {
        setError('No place found. Enter a place name, or a coordinate as latitude, longitude.')
      }
      return
    }
    const result = parseCoordinates(text)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    combobox.close()
    onGo(result.value)
  }

  return (
    <div {...combobox.rootProps} className="relative w-[18rem]">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
        aria-label="Go to a place or coordinates"
        className="flex flex-col gap-2 rounded-md border border-border bg-background/95 p-2 backdrop-blur"
      >
        <label
          htmlFor={inputId}
          className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
        >
          Place or coordinates
        </label>

        <div className="flex gap-2">
          <Input
            id={inputId}
            value={text}
            onChange={(event) => {
              setText(event.target.value)
              combobox.reopen()
              // Clear the error as soon as the input changes: keeping it while
              // someone is fixing the value reads as if the fix did not register.
              if (error) setError(null)
            }}
            placeholder="Beirut, or 33.8938, 35.5018"
            inputMode="text"
            aria-label="Place or coordinates"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className="h-8"
            {...combobox.inputProps}
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

      {combobox.open ? (
        <ComboboxPopup blur>
          <PlaceOptions
            state={search}
            listId={combobox.listId}
            optionProps={combobox.optionProps}
            activeIndex={combobox.activeIndex}
          />
        </ComboboxPopup>
      ) : null}
    </div>
  )
}
