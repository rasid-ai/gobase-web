import { useEffect, useState } from 'react'

/**
 * Bridges design tokens into MapLibre.
 *
 * Tailwind projects the map tokens into utility classes via `@theme inline`
 * (src/styles/tokens.css), but MapLibre paint properties are not classes — they
 * need real colour values. So we read the custom properties off the document
 * and hand MapLibre the resolved result, which keeps the rule in CLAUDE.md
 * intact: tokens only, never a hardcoded colour.
 */
export type MapTokens = {
  result: string
  footprint: string
  selection: string
}

const TOKENS = {
  result: '--map-result',
  footprint: '--map-footprint',
  selection: '--map-selection',
} as const

/**
 * Normalise any CSS colour to something MapLibre's parser accepts.
 *
 * The tokens are authored in oklch, which MapLibre's style validator rejects
 * outright. Canvas understands it, so we paint a single pixel and read the
 * channels back — that converts through the browser rather than shipping a
 * colour-space implementation of our own.
 */
function resolve(value: string): string {
  if (!value) return value
  const canvas = document.createElement('canvas')
  canvas.width = 1
  canvas.height = 1
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return value

  context.fillStyle = value
  context.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${a / 255})`
}

function read(): MapTokens {
  const styles = getComputedStyle(document.documentElement)
  const of = (name: string) => resolve(styles.getPropertyValue(name).trim())
  return {
    result: of(TOKENS.result),
    footprint: of(TOKENS.footprint),
    selection: of(TOKENS.selection),
  }
}

/** The current token colours, re-read whenever the theme changes. */
export function useMapTokens(): MapTokens {
  const [tokens, setTokens] = useState<MapTokens>(read)

  useEffect(() => {
    // The theme swaps by toggling a class on <html>; every token changes with it.
    const observer = new MutationObserver(() => setTokens(read()))
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    })

    // matchMedia is absent outside a browser (jsdom, SSR); the class observer
    // above still covers an explicit theme choice.
    const scheme = window.matchMedia?.('(prefers-color-scheme: dark)')
    const onScheme = () => setTokens(read())
    scheme?.addEventListener('change', onScheme)

    return () => {
      observer.disconnect()
      scheme?.removeEventListener('change', onScheme)
    }
  }, [])

  return tokens
}
