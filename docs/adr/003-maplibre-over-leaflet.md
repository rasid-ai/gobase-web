# ADR-003: MapLibre GL, not Leaflet

**Status:** Accepted · 2026-09-01

## Context

The map page renders query-result vector layers (its main function),
asset footprints/coverage on click, and area selection for spatially
scoped questions. Raster (COG tile) display comes in a later phase.
React is fixed; react-map-gl supports both candidates.

## Decision

MapLibre GL, via react-map-gl, with terra-draw for area selection.

## Why

- Result layers are the core job, and their size is not under our control
  — MapLibre renders vectors via WebGL and handles thousands of features;
  Leaflet's DOM rendering degrades well before that.
- H3 aggregation layers and any future vector tiles are native territory.
- The phase-two raster path (titiler XYZ tiles) works equally in both, so
  it doesn't distinguish them — the vector story does.

## Rejected

**Leaflet** — simpler API, bigger plugin ecosystem, easier handover to
developers who know it. Defensible if result layers were guaranteed
small; they aren't.

## Revisit when

Practically never for this app; the cost of being wrong here is a page
rewrite, so the decision was made before the first map component.
