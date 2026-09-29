# Esri — turning typed text into somewhere on the map

Esri's ArcGIS World Geocoding Service answers "where is this?" for an
address or a place name. It is the only service the portal talks to that
this team does not run, and the only one with a bill attached
(docs/adr/011).

Only `backend/apps/places/esri.py` speaks to it. Everything above that
module handles a *place* — a name, a latitude, a longitude and a bbox —
and would not change if the geocoder did. The frontend never reaches it
at all; it calls `GET /api/places/search` like any other portal endpoint.

## Connecting

`POST {ESRI_GEOCODE_URL}/findAddressCandidates`, one call per search.

A **POST with a form body, not a GET with a query string**, and that is
not a style choice: the API key is one of the fields. In a query string
it lands in every proxy log between here and there, and comes back out
inside `httpx`'s own exception text. Esri accepts either method.

| Setting | Local default | What it is |
|---|---|---|
| `ESRI_GEOCODE_URL` | `https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer` | The service root. `/findAddressCandidates` is appended. |
| `ESRI_API_KEY` | *(blank)* | An ArcGIS Location Platform API key. **Blank is a supported state**, not a broken one — see below. |
| `ESRI_TIMEOUT_SECONDS` | `5` | Per-request timeout. |
| `ESRI_MAX_CANDIDATES` | `5` | How many candidates one search may offer. |

Named in `backend/.env.example` and `infra/.env.example`, blank key
included. Every one carries a default in `config/settings.py`, because
CI's contract job sets no environment variables at all.

### A blank key is a state the portal supports

With no key, `GET /api/places/search` answers **503 before opening a
socket**, and both search boxes say *Address search is unavailable*. The
portal runs perfectly well without an ArcGIS account — it simply cannot
do this one thing. That is what lets the whole feature be built, tested
and reviewed before anyone signs up.

The frontend latches on that 503: a service that is switched off will
not be switched on three keystrokes later, so it is asked once a session
rather than once a character.

**Two things to know when a key is first added**, both of which look like
the key not working:

- **Restart the backend.** Settings are read once at startup, and Django's
  auto-reloader watches `.py` files, not `.env`. A running server keeps the
  blank key it started with.
- **Reload the page.** The latch above is per page load, so a tab that has
  already seen a 503 will not ask again however many times you type.

## The request

```
f=json
singleLine=<what was typed>
maxLocations=<ESRI_MAX_CANDIDATES>
outFields=
outSR=4326
forStorage=false
token=<ESRI_API_KEY>
```

`outSR=4326` is explicit so the service default cannot drift away from
the SRID everything else in the portal uses. `outFields=` asks for
nothing beyond the address, the point and the extent, because nothing
beyond those is used. `forStorage=false` is the free tier — see Cost.

**No country code and no search extent.** The geocoder is worldwide and
unbiased, because the catalog holds Dresden assets as well as Lebanese
ones and a Lebanon restriction would make the feature useless against a
third of the data.

## The answer, and its two failure modes

A candidate that matters looks like:

```json
{
  "address": "Beirut, Lebanon",
  "location": { "x": 35.5018, "y": 33.8938 },
  "extent": { "xmin": 35.4, "ymin": 33.8, "xmax": 35.6, "ymax": 34.0 }
}
```

Three quirks the client handles, each with a test:

- **A rejected request comes back as HTTP 200 with an `error` object.**
  An expired or missing token is reported this way. That is the geocoder
  *answering*, not the geocoder being down, so the body is read before
  the status code — the same rule `apps/runs/dagster.py` follows.
- **A candidate may have no `location`.** It is dropped rather than
  offered as a row that would do nothing when picked.
- **An extent may come back inside-out** (`xmin > xmax`) for a place
  spanning the antimeridian. Neither half is the place, so the portal
  reports no area and keeps the point.

Failures map to two exceptions, and the view turns them into HTTP:

| Exception | HTTP | When |
|---|---|---|
| `EsriUnavailable` | 503 | Refused, unresolved, timed out, no JSON — or no API key |
| `EsriError` | 502 | Answered with an `error` object |

`EsriUnavailable` carries the exception's *type*, never its message,
because an `httpx` message carries the URL and the URL is one refactor
away from carrying the key. And unlike the Dagster proxy, **the 502 does
not pass the upstream message on**: Dagster's error branches describe the
caller's own request, so a caller can act on them; Esri's describe our
credentials, which is configuration aimed at someone who cannot fix it.
It goes to the log.

## Cost, and why nothing is cached

Esri prices geocoding by results returned, in two tiers:

| Tier | Free allowance | After that |
|---|---|---|
| Not stored | 20,000 / month | $0.50 per 1,000 |
| Stored | **none** | $4.00 per 1,000 |

A cache is storage. Caching geocode results would move the portal from
the free tier to the one with no free allowance, to save requests it was
not being charged for — so nothing is cached, and `forStorage=false` says
so on every call (docs/adr/011). The brakes are all in the client: a
300 ms debounce, a three-character minimum, and text that parses as a
coordinate never reaching the geocoder at all.

## Known next step

**There is no server-side throttle.** Every brake above is in the
browser, so any authenticated caller can ask in a loop. DRF's
`ScopedRateThrottle` is the one-line fix; it has not been added because
nothing yet warrants it. Add it before the free tier is anywhere near.

## Open — settle before a key is issued

ArcGIS location-service terms have historically carried conditions about
which basemaps geocoding results may be displayed over, and this portal
draws OpenStreetMap raster tiles. **Confirm this with whoever owns the
ArcGIS account before signing up.** It does not block building, which is
why the blank-key path exists; it blocks shipping.
