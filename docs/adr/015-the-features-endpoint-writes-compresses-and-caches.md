# ADR-015: The features endpoint writes, compresses and caches its own body

**Status:** Accepted · 2026-09-24

## Context

A 10,000-feature page from `GET /api/map/assets/{id}/data` took 731–946 ms on
the server and went out as 5.2 MB of uncompressed JSON. Measured, almost none
of that was reading the lake. The scan was ~12%. The rest was one geometry
taking a pointless round trip: DuckDB wrote it as GeoJSON text, Python parsed
it back into objects, built a dict per feature, and DRF's renderer serialised
the lot into the same text again.

Nothing on the API path compressed anything — no `GZipMiddleware`, no gzip in
the host nginx vhost — although GeoJSON compresses 4.7× (buildings) to 7.8×
(roads).

And the browser did not cache as believed. Coming back to a window already
read showed the cached features and then quietly downloaded every page again,
because React Query treats data as stale at once by default. A test showed two
requests where there should have been one.

## Decision

**One endpoint stops going through DRF's renderer: it writes its own body,
compresses it, and makes it cacheable.**

### DuckDB writes the page

The page's GeoJSON is built inside the query — `ST_AsGeoJSON`, `to_json`,
`string_agg` — and written into the response as text. No feature becomes a
Python object. 188 ms for the same 10,000 features, and identical output on
every active asset that could be read before.

The output is guaranteed to be JSON a browser accepts: NaN and infinity become
`null` (`to_json` writes them bare, as Python's `json` did before), and a file
with no attribute columns gets `{}`. Two assets that could not be read at all —
a zoned timestamp needs `pytz` to become a Python `datetime` — now read,
because no value leaves DuckDB.

`AssetDataSerializer` still declares the response shape, so the contract and
the generated client are unchanged. It no longer renders anything.

### Gzip, at level 1, on this endpoint only

- **Not site-wide.** Django's `GZipMiddleware` also compresses streaming
  responses, which would hold back the server-sent events the Ask slice will
  use. And compressing only this keeps compression away from any response
  that carries a secret (BREACH) — this body carries none.
- **Not `gzip_page` either.** It compresses at level 6 with no way to change
  it, and at level 6 compression cost more than building the page: 315 ms for
  1.17 MB. Level 1 costs 90 ms for 1.29 MB. So the view compresses itself, in
  about ten lines.

### Caching, in two layers

- **In the session:** feature queries are never stale (`staleTime: Infinity`).
  Coming back to a window is a cache hit with no request. `gcTime` stays at
  its default, so windows left behind are dropped after five minutes and
  memory stays bounded.
- **Across reloads:** the response carries an ETag and
  `Cache-Control: private, no-cache`. The browser keeps the page and asks
  before reusing it; a matching ETag is answered with an empty 304 in about
  2 ms — one catalog lookup, no lake read, no payload.

Both rest on one fact: **assets are content-addressed.** Changed content gets
a new `asset_id` and the old one is superseded (`assets.content_hash`;
verified against the 2026-09-24 silver rewrite, where all 12 changed files got
new ids). So the asset id plus the request decide the body completely, and the
ETag is computed from them without reading anything.

The ETag is checked *after* the catalog lookup, so a superseded asset answers
404 rather than blessing an old copy. Authentication runs before either, so a
kept copy is never confirmed to someone signed out.

## Measured

A 10,000-building page over Beirut, through the view:

| | before | after |
|---|---|---|
| server time | 731–946 ms | 273 ms, gzip included |
| bytes sent | 5.2 MB | 1.29 MB |
| coming back to a window, same session | every page again | nothing |
| reloading onto a window | every page again | 304, 0 bytes, ~2 ms |

## Rejected

**A long `max-age`, or `immutable`.** Cheaper than revalidating — no request at
all. Rejected because the URL does not change when the response format does,
so a browser would go on serving an old shape after a deploy until the
max-age ran out. With an ETag, bumping `FEATURES_FORMAT` invalidates every
copy at once.

**orjson.** Would speed up Python's half of the old path. Rejected because the
new path has no Python half: nothing is parsed or serialised in Python at all.

**Persisting the React Query cache to IndexedDB.** Survives reloads without a
request. Rejected: tens of megabytes of GeoJSON in IndexedDB per session, and
the ETag gets almost the same effect for a round trip.

**Gzip in the host nginx.** Faster (C, and off the Python workers) and the
usual place for it. Not done here because the vhost is not in this repo and
would not compress in development. Worth moving there if the Python workers
become the bottleneck; the view would then stop compressing.

## Consequences accepted

- **`FEATURES_FORMAT` has to be bumped** whenever the same request could get a
  different body — a change to the response shape, to how the lake read
  filters, or to how a value is written. Forgetting leaves browsers serving the
  old body while the ETag still matches. It is the price of answering 304
  without reading anything.
- **This endpoint differs from every other.** It writes its own body, sets its
  own headers, and compresses itself. The view says so and points here.
- **Behaviour changes from the old path:** decimals are now numbers, not text;
  NaN and infinity are `null`, not invalid JSON; zoned timestamps read, as
  text. No active asset had a decimal or a NaN.

## Would vector tiles conflict with this?

No — the two layers of caching fare differently, and neither is in the way.

- **The HTTP layer carries over directly.** Tiles are the textbook case for it:
  a fixed URL per tile (`/{z}/{x}/{y}`), content fixed by the asset id, so the
  same ETag — or even a long max-age behind a versioned URL — applies. MapLibre
  fetches tiles through the browser's HTTP cache like any other request; the
  token would be attached with `transformRequest`.
- **The React Query layer would simply stop applying** to a tiled layer.
  MapLibre fetches, caches and evicts tiles itself, so `useAssetFeatures`, the
  snapped windows and `staleTime` would be replaced for that layer, not fought.
- **The real friction is elsewhere: drawn areas.** A tile knows nothing about a
  polygon the user drew, so exact area filtering (ADR-014) would have to move
  to the client or into a per-area tile URL — which would multiply the tile
  cache by the number of areas. That is the thing to design when tiles come,
  not the caching.

## Revisit when

The response format changes — bump `FEATURES_FORMAT`. The Python workers are
the bottleneck — move compression to nginx. Vector tiles arrive — the ETag
approach extends to the tile endpoint, and the drawn-area question above is
the one to solve.
