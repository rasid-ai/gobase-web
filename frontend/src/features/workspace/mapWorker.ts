import { setWorkerUrl } from 'maplibre-gl'
// `?url` makes Vite emit the worker as a real asset and hands back its final
// URL. Importing it by path is the whole point: MapLibre otherwise builds the
// URL itself at runtime, from its own module location and a filename it picks
// dynamically (`-dev` or not), which no bundler can follow.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

/**
 * Tell MapLibre where its GeoJSON worker lives.
 *
 * Without this nothing backed by a geojson source ever renders — not asset
 * footprints, not drawn vector layers — and there is no error, because the
 * failed request is made by the worker loader rather than by the map. The
 * raster basemap keeps working, which makes it look like a bug in whatever was
 * drawn last.
 *
 * Imported for its side effect, and it must run before the first map is
 * constructed.
 */
setWorkerUrl(workerUrl)
