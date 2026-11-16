/** The draw tool's teardown: specs/map.md, docs/adr/014. */

import { render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { DrawArea } from './DrawArea'

const tool = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  setMode: vi.fn(),
  on: vi.fn(),
}))

// terra-draw needs a real MapLibre map; the tool is replaced with one that
// records what it was asked to do.
vi.mock('terra-draw', () => ({
  TerraDraw: vi.fn(function TerraDraw() {
    return tool
  }),
  TerraDrawPolygonMode: vi.fn(),
  ValidateNotSelfIntersecting: vi.fn(),
}))
vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: vi.fn(),
}))

/** A map that can be removed, as react-map-gl removes it when the page goes. */
function fakeMap() {
  const listeners = new Map<string, () => void>()
  const map = {
    doubleClickZoom: { enable: vi.fn(), disable: vi.fn() },
    once: (event: string, listener: () => void) => listeners.set(event, listener),
    off: (event: string) => listeners.delete(event),
    remove: () => listeners.get('remove')?.(),
  }
  return map
}

function mount(map: ReturnType<typeof fakeMap>, active = true) {
  const mapRef = { current: { getMap: () => map } } as never
  return render(
    <DrawArea
      mapRef={mapRef}
      ready
      active={active}
      color="#000000"
      onDrawn={() => {}}
      onRefused={() => {}}
    />,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.clearAllMocks()
})

it('stops the tool when draw-area mode ends', () => {
  const map = fakeMap()
  const view = mount(map)

  view.rerender(
    <DrawArea
      mapRef={{ current: { getMap: () => map } } as never}
      ready
      active={false}
      color="#000000"
      onDrawn={() => {}}
      onRefused={() => {}}
    />,
  )

  expect(tool.stop).toHaveBeenCalledOnce()
  expect(map.doubleClickZoom.enable).toHaveBeenCalledOnce()
})

it('leaves a removed map alone, rather than throwing as the page goes', () => {
  // Going from the map to Assets in draw-area mode removes the map first.
  // Stopping the tool then wrote to sources that were gone, and the error
  // blanked the whole app.
  const map = fakeMap()
  const view = mount(map)

  map.remove()
  view.unmount()

  expect(tool.stop).not.toHaveBeenCalled()
})
