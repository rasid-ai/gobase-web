import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent, RefObject } from 'react'

/**
 * The behaviour of a text box that offers a list of options beneath it.
 *
 * Built here rather than pulled in: the only Radix packages this app has are
 * dialog, label and slot, and one control does not justify another dependency
 * — the same call `ui/Toast` made.
 *
 * It knows nothing about what the options are or where they came from. It owns
 * the ids, the highlight, the keyboard map, and closing on an outside click or
 * Escape. Follows the ARIA 1.2 combobox pattern: focus never leaves the input,
 * and `aria-activedescendant` is what moves.
 */
export function useCombobox({
  count,
  onSelect,
  onSubmit,
  hasPopup,
}: {
  /** How many options exist right now. */
  count: number
  onSelect: (index: number) => void
  /** Enter with nothing highlighted. The map's coordinate box owns this. */
  onSubmit?: () => void
  /** Whether there is anything at all to show — a message counts. */
  hasPopup: boolean
}) {
  const base = useId()
  const listId = `${base}-list`
  const optionId = useCallback((index: number) => `${base}-option-${index}`, [base])

  const [dismissed, setDismissed] = useState(false)
  const [activeIndex, setActiveIndex] = useState<number | null>(null)
  const root = useRef<HTMLDivElement>(null)

  const open = hasPopup && !dismissed

  // A new result set must not leave the highlight pointing at the old third
  // row, which is now something else. Tracked against the count it was chosen
  // under, so the reset happens in render rather than a frame later.
  const [countWhenChosen, setCountWhenChosen] = useState(count)
  if (countWhenChosen !== count) {
    setCountWhenChosen(count)
    setActiveIndex(null)
  }

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: globalThis.PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setDismissed(true)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  const close = useCallback(() => {
    setDismissed(true)
    setActiveIndex(null)
  }, [])

  /** Call when the text changes: a fresh query deserves a fresh popup. */
  const reopen = useCallback(() => {
    setDismissed(false)
    setActiveIndex(null)
  }, [])

  const select = useCallback(
    (index: number) => {
      onSelect(index)
      close()
    },
    [onSelect, close],
  )

  const step = (by: number) => {
    if (count === 0) return
    setActiveIndex((current) => {
      if (current === null) return by > 0 ? 0 : count - 1
      return (current + by + count) % count
    })
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setDismissed(false)
      step(event.key === 'ArrowDown' ? 1 : -1)
      return
    }
    if (event.key === 'Home' || event.key === 'End') {
      if (!open || count === 0) return
      event.preventDefault()
      setActiveIndex(event.key === 'Home' ? 0 : count - 1)
      return
    }
    if (event.key === 'Enter') {
      if (open && activeIndex !== null) {
        event.preventDefault()
        select(activeIndex)
        return
      }
      // Deliberately not prevented: on the map this is a form submit, and the
      // coordinate path owns it.
      onSubmit?.()
      return
    }
    if (event.key === 'Escape') {
      if (!open) return
      event.preventDefault()
      close()
      return
    }
    if (event.key === 'Tab' && open) close()
  }

  return {
    open,
    activeIndex,
    close,
    reopen,
    listId,
    optionId,
    rootProps: { ref: root as RefObject<HTMLDivElement> },
    inputProps: {
      role: 'combobox' as const,
      'aria-expanded': open,
      'aria-controls': listId,
      'aria-autocomplete': 'list' as const,
      'aria-activedescendant': activeIndex === null ? undefined : optionId(activeIndex),
      onKeyDown,
    },
    optionProps: (index: number) => ({
      id: optionId(index),
      role: 'option' as const,
      'aria-selected': index === activeIndex,
      // pointerdown, not click: a click on a row fires after the input has
      // blurred, by which time a blur handler may have unmounted the row.
      onPointerDown: (event: PointerEvent) => {
        event.preventDefault()
        select(index)
      },
      onPointerEnter: () => setActiveIndex(index),
    }),
  }
}
