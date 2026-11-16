# ADR-032: The backend image installs libexpat for rasterio

**Status:** Accepted · 2026-11-16
**Changes:** docs/adr/029, its line "the image needs no system package"

## Context

ADR-029 said the `rasterio` 1.5.1 wheel bundles GDAL and PROJ, so the
backend image needs no system package. That was wrong. The wheel links
`libexpat` (a small XML parser library) but does not bundle it, and
`python:3.12-slim` does not have it.

It worked on the laptop because the laptop has `libexpat1` installed. On the
VM, with image `f63a141`, `import rasterio` raised `ImportError:
libexpat.so.1`. So every `raster-stats` and `clip.tif` call returned 500, and
the Ask agent's raster tool failed. The deploy still looked healthy: the
health check never imports `rasterio`, because `apps/map/raster.py` imports
it on first use.

## Decision

- `backend/Dockerfile` installs `libexpat1` with apt, next to `curl`.
- The build runs `python -c "import rasterio"` right after `pip install`. If
  any shared library `rasterio` needs is missing, the build fails, not the
  first raster request.

The rest of ADR-029 stands.

## Consequences

- The image grows by a few hundred KB.
- A `rasterio` upgrade that needs another system library fails the build,
  which shows the missing library's name.
- The import check covers `rasterio` only. Another wheel that is imported on
  first use could still miss a library at run time.
