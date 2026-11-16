import { setWorkerUrl } from 'maplibre-gl'
// `?worker&url`, not `?url`. Both emit a file and hand back its URL, but `?url`
// copies that one file alone — and MapLibre's worker imports
// `./maplibre-gl-shared.mjs`, which then 404s and takes the worker down with
// it. `?worker` bundles the worker together with what it imports.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

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
