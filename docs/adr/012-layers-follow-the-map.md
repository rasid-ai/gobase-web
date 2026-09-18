# ADR-012: Drawn layers follow the map, and features are read per area

**Status:** Accepted · 2026-09-18

Replaces one consequence of ADR-008: "hiding a layer is a paint change,
never a refetch. The features are already in the store." Hiding is still a
paint change. But the features are no longer in the store, and moving the
map is now a read. ADR-008 stands in every other respect.

## Context

`GET /api/map/assets/{id}/data` returned at most `LAKE_MAX_FEATURES`
features — 5000 — and there was no way to see the rest. The cap fired on
real data. A layer with more features than that was quietly incomplete,
and the only thing the portal could say about it was "showing first 5000".

Raising the number does not fix it. The cost of a large layer is not
drawing: MapLibre already paints only what is on screen. The cost is the
JSON on the wire, `JSON.parse`, the worker building a spatial index, and
the memory the FeatureCollection sits in. Paging the same total into the
browser moves the same bytes in smaller trucks and arrives at the same
place, with more round trips.

The catalog holds 34 active vector assets. The largest,
`lebanon_buildings_full.parquet`, holds **1,012,407 features**; roads holds
148,925. Reading the buildings file whole takes 27 seconds. A user looking at
one street does not need the other million.

## Decision

**A drawn layer is read for the area the map is showing, and read again
when that area changes.**

- `bbox` is a query parameter on the data endpoint, and the server does
  not care where it came from. The map's camera produces it today; the
  draw-an-area feature will produce it later without changing the API.
  Swapping `ST_MakeEnvelope` for `ST_GeomFromGeoJSON` is what it would take
  to accept a real polygon rather than a rectangle.
- **The window is not the viewport.** It is the viewport padded and
  snapped outward onto a grid whose cell size tracks the zoom
  (`windowFor`). It always covers the viewport, so there is never an
  unfilled strip at the edge of the screen. Small pans land on the same
  window, which means the same query key, which means the cache answers
  and nothing is fetched.
- **The camera never reaches the URL.** `?bbox=` already means the area
  the *user* chose — a searched place today, a drawn box later (ADR-011) —
  and one parameter cannot carry both. A pan would also rewrite history on
  every move.
- **Only visible layers read.** Hiding stays free, as ADR-008 requires. A
  hidden layer keeps whatever the cache holds and reads again when shown.
- **Paging inside a window is keyset on `file_row_number`, not offset.**
  `read_parquet` has no inherent order and DuckDB scans in parallel, so an
  offset would repeat some rows and skip others between pages — the hazard
  `catalog/kb.py` already documents for the asset list.
- **A budget, not a cap.** The client reads at most `PAGE_BUDGET` pages
  per window and then stops, saying so. Zooming in makes the next window
  smaller, so the layer comes back whole. This replaces `truncated`, which
  meant "the file is bigger than the server will ever return" — a dead end.
  `next_cursor` on the wire says the same thing more precisely, so
  `truncated` left the API and is derived in the client.
- **A failed read belongs to the layer, not to the moment.** It shows in
  the layers panel, not as a toast. A layer re-reads on every move, and a
  toast per failed pan would be noise.

## Rejected

**Paging the whole asset into the browser.** What was first asked for, and
the smallest change to the client. Rejected because it fixes the one thing
that was not broken. The browser still ends up holding every feature, with
the same parse cost and the same memory, after ten round trips instead of
one.

**Vector tiles (MVT) from `ST_AsMVT`.** The right answer at real scale, and
ADR-003 already calls tiles "native territory" for MapLibre. Rejected for
now, not on the merits: it needs a tile cache, per-zoom generalisation and
a second source type in the client, none of which exist, while this change
is a query parameter and a hook. At the measured scale it is the better
design and this one is the affordable one. See "revisit now" below — the
gap between those two is not comfortable.

**Simplifying geometry at low zoom.** Honest at every zoom and prettier
than a budget. Rejected because it makes the portal show data the file does
not contain, and needs per-zoom tuning nobody has done. "Zoom in for the
rest" is a worse experience and a true statement.

**An explicit "refresh in this view" button.** Keeps ADR-008 intact and
makes every read deliberate. Rejected because it makes panning feel broken:
you see the edge of the last window and a blank beyond it.

## Consequences accepted

- **Every window is a full scan of the file.** These GeoParquet files have
  no bbox covering column, so every row is looked at whatever the window is;
  the filter saves serialisation and transfer, not I/O. There is a floor
  under every area query. On the 1M-feature buildings layer that floor is
  ~340ms at street zoom, rising to ~1.4s for the whole country. **This
  ceiling is already being reached** — see "revisit now" below, which is not
  a future condition.
- **The area filter matches bounding boxes, not exact geometry.**
  `ST_Intersects_Extent` rather than `ST_Intersects`, measured 18-40% faster
  with identical results on the real layers. It is over-inclusive and never
  under-inclusive, which is free for drawing and is stated in the endpoint's
  contract, because anything that counts from it needs to know.
- **Each page is a separate scan.** DuckDB keeps no result between
  requests. The cursor is a range filter rather than an offset, so a later
  page is never worse than the first. Without an area filter that makes
  paging nearly free, because the scan stops as soon as it has enough rows:
  measured flat at 27-34ms per page on the 1M-feature layer. **With an area
  filter it does not**, because nothing lets the scan stop early — page two
  of a country-wide window cost 1.9s, the same as page one. This is why the
  page size is large enough that one page is the normal case, and why the
  budget is two.
- **One pan fires one request per visible layer.** Draw six layers and a
  settled move is six requests. They are parallel and deduplicated by
  query key, but the number grows with the layer count.

## Revisit now, not later

This was written expecting the largest asset to hold under 50,000 features.
Measured against the real catalog it holds **1,012,407**, so the condition
that was meant to trigger a rethink is already true on the day this was
accepted.

What that changes: the design stands — a 340ms street-zoom read beats a
27-second one, and there is no version of this that does better without new
work. What it does not do is leave headroom. The buildings layer at country
zoom costs ~1.4s per page per pan, and the budget allows two pages.

The two ways out, in order of cost:

1. **bbox covering columns in the GeoParquet** (GeoParquet 1.1). Row groups
   become prunable and the floor disappears. This is a change in the data
   platform repo, not here, and it needs nothing new in the portal.
2. **Vector tiles** (`ST_AsMVT`), as ADR-003 anticipated. A bigger change
   here: tile cache, per-zoom generalisation, a second source type.

Until one of those lands, the honest tuning knob is `PAGE_BUDGET` in
`useAssetFeatures.ts`.
