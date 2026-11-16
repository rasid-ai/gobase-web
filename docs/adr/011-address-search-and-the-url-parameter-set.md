# ADR-011: Address search, the first outside service, and the URL parameter set

**Status:** Accepted · 2026-09-18

## Context

The portal could find a place only if you already knew its coordinates.
Address search turns typed text into somewhere on the map, on the Atlas
page and on the Assets page, and it is what `specs/assets.md` named as
the thing that would bring filtering by area with it.

Three decisions had to be made before any of it could be built, and each
reaches past the feature.

**No geocoder lives here.** Every outside system the portal speaks to so
far is one this team runs: Dagster on localhost, Postgres on the host,
object storage over Tailscale. A geocoder is somebody else's service,
with somebody else's bill and terms. There is no precedent for one.

**Two pages need it and neither owns it.** `apps/map` already means
*the assets covering this point*, and the Assets page has no map on it.
`apps/catalog/kb.py` is by its own docstring the only module that knows
the knowledge base's tables, and geocoding touches none.

**The area has to cross between the pages.** ADR-009 said that when the
workspace needs more of its state in the URL than one asset id — a drawn
area among them — "the parameter set deserves designing rather than
growing". This is that moment.

## Decision

**A new `apps/places`, serving `GET /api/places/search?q=`.** One
module, `apps/places/esri.py`, speaks to the geocoder and nothing above
it names a vendor: a candidate is a name, a latitude, a longitude and a
bbox. Swapping geocoder is one file.

**Esri's `findAddressCandidates`, one call per search, up to five
candidates.** Each candidate carries its own extent, so an area comes
back with the point and nothing has to be asked twice. Esri's `/suggest`
is the richer typeahead and was rejected: it needs a second call before
a pick can resolve, for suggestions that are better but not better
enough to pay two round trips for.

**Nothing is cached.** Esri prices geocoding in two tiers: *not stored*
is free to 20,000 a month and $0.50 per 1,000 after, *stored* has no free
allowance at all and costs $4.00 per 1,000. A cache is storage. The
portal also has no cache infrastructure of any kind, so this would be new
infrastructure to make the feature cost more. The client debounces
instead, waits for three characters, and never asks about text that
parses as a coordinate.

**A blank `ESRI_API_KEY` is a supported state, not a broken one.** The
endpoint answers 503 before opening a socket and the pages say address
search is unavailable. The portal runs without an ArcGIS account; it
just cannot do this one thing.

**The key travels in a POST body, never a query string.** Esri accepts
either. A key in a request line reaches proxy logs, and comes back out
inside `httpx`'s own exception text — so `EsriUnavailable` carries the
exception's type and not its message.

**A parameter exists if, and only if, the state has to cross a page
boundary.** That is the whole rule, and it gives the set:

| parameter | pages | why |
|---|---|---|
| `asset=<uuid>` | `/map` | crosses Assets → Map |
| `place=<name>` | both | what to call the area |
| `bbox=minLon,minLat,maxLon,maxLat` | both | crosses Map ↔ Assets |

**`bbox` is the state and `place` is its label.** `place` without `bbox`
filters nothing and is dropped. `bbox` without `place` is a hand-written
link and works, shown as the box itself. A `bbox` that cannot be read is
removed from the URL, reported once in a toast, and the page renders
unfiltered.

**The area filter is `ST_Intersects` inside the browse CTE**, so the
page, the total and the per-type counts are narrowed together.

## Why

- **The frontend cannot call a geocoder directly.** It would carry the
  key, and CLAUDE.md forbids it reaching third parties at all.
- **Counts that ignore the area would describe a catalog nobody is
  looking at.** ADR-010 excludes exactly one axis from the type counts,
  the type filter, and its reason is self-referential: folding a filter
  into its own counts leaves each one either itself or zero, which says
  nothing. No other filter has that property. `q` and the ingestion
  window already narrow the counts; the area joins them. Otherwise an
  empty grid sits beside a rail reading `vector 34`, which reads as a
  broken page.
- **`ST_Intersects` over the `&&` box operator.** Every extent in the
  live catalog is a valid rectangle today, so the two agree; the precise
  test costs nothing, because PostGIS puts a box index condition in front
  of it anyway and the GiST index on `extent` is used either way. It also
  stays correct if extents ever become real footprints.
- **Stating the URL rule rather than the list** decides the next case
  without another ADR, and explains the absences, which is the harder
  half: `q`, the data types, the ingestion window, the sort, the page
  number, the map's mode, its marker and its drawn layers all stay in
  component state, because none of them leaves its page.
- **A broken `bbox` is said out loud** because silently widening someone
  else's link from one city to the whole catalog looks exactly like a
  filter that does not work.

## Consequences, including one that is awkward

**A `/map` link restores the framing and the name, not the marker or the
panel.** The parameters describe an *area*; the marker and the
assets-at-point list are the result of an action. This is the same shape
`specs/map.md` already records for `?asset=` — "there is no point marker,
because no point was chosen" — but it is the weakest joint in the design
and is the first thing to re-open. The alternative, should it grate, is
that the map reads the pair and never writes it, and only the Assets page
generates it.

**"The frontend never talks to a third party" already had an exception**
before this ADR: the basemap fetches raster tiles straight from
`tile.openstreetmap.org`. The rule is about credentials and about data,
not about every byte a browser pulls. Stated plainly so nobody "fixes"
the basemap next: **anything carrying a credential, or returning data
about the knowledge base, goes through the backend.**

**The endpoint has no server-side throttle.** The three-character
minimum, the debounce and the coordinate short-circuit are all in the
client, so any authenticated caller can ask in a loop. DRF's
`ScopedRateThrottle` is the one-line fix when usage warrants it.

## Open

**Esri's terms of use are unconfirmed.** The free tier is on their
pricing page, but ArcGIS location-service terms have historically carried
conditions about which basemap results may be displayed over, and this
portal draws OpenStreetMap tiles. This must be settled with whoever owns
the ArcGIS account **before a key is issued**. It does not block
building; it blocks shipping.

## Rejected

**Nominatim or another keyless geocoder** — no key to manage, but a
stricter usage policy, and the portal is already in breach of OSM's tile
attribution policy (`diary/2026-09-08.md`). Adding a second obligation to
the same family before honouring the first is not a trade worth making.

**`postgis_tiger_geocoder`, which is installed in `kb`** — no data is
loaded, `kb` is read-only to the portal so none could be, and TIGER is
United States only while the map opens on Lebanon.

**Restricting the geocoder to Lebanon** — the catalog holds Dresden
assets as well as Lebanese ones, so a country restriction would make
address search useless against a third of the data.

## Revisit when

The geocoder's bill stops being free, at which point caching and its
licence become one question rather than two; or a third page needs the
area, at which point the parameter rule above is what decides it.
