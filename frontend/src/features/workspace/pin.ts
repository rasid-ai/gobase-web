/**
 * The marker drawn for each point feature of a drawn layer: a map pin with a
 * hole, in the map's result colour (a design token, resolved by mapTokens).
 *
 * Drawn on a canvas, not shipped as a file, so its colour follows the token
 * and the theme. 2x pixels for sharp edges; MapLibre shows it at 20 x 26 CSS
 * pixels, its tip on the point (`icon-anchor: bottom`).
 */
export const PIN_IMAGE = 'asset-pin'
export const PIN_PIXEL_RATIO = 2

const WIDTH = 40
const HEIGHT = 52

export function pinImage(color: string): ImageData | null {
  const canvas = document.createElement('canvas')
  canvas.width = WIDTH
  canvas.height = HEIGHT
  const context = canvas.getContext('2d')
  if (!context) return null

  const cx = WIDTH / 2
  const cy = 18
  const r = 16
  // A circle drawn into a point at the bottom: the two tangents from the tip.
  context.beginPath()
  context.moveTo(cx, HEIGHT - 2)
  context.arc(cx, cy, r, Math.PI * 0.82, Math.PI * 0.18)
  context.closePath()
  context.fillStyle = color
  context.fill()

  // The hole, punched through so the map shows inside it.
  context.globalCompositeOperation = 'destination-out'
  context.beginPath()
  context.arc(cx, cy, 6, 0, Math.PI * 2)
  context.fill()

  return context.getImageData(0, 0, WIDTH, HEIGHT)
}
