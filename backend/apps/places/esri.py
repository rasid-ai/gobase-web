"""The only module that speaks to the geocoder.

Everything above this speaks in portal terms: a name, a latitude, a longitude,
and a bounding box in the same four-number order the catalog already uses. The
vendor is named here and nowhere else, so changing geocoder is one file.

The service and its quirks are documented in context/integrations/esri.md;
docs/adr/011 explains why the portal proxies it rather than letting the browser
call it, and why nothing is cached.
"""

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class EsriUnavailable(Exception):
    """The geocoder could not be reached at all: refused, unresolved, or too slow."""


class EsriError(Exception):
    """The geocoder answered, but with an error object instead of candidates."""


def find_places(text: str, limit: int | None = None) -> list[dict]:
    """Candidate places for one line of typed text, best first.

    No matches is an empty list, not an error: "nothing is called that" is an
    answer, the same way an uncovered point is (specs/map.md).
    """
    payload = _post(text, limit or settings.ESRI_MAX_CANDIDATES)
    found = (_place(candidate) for candidate in payload.get("candidates") or [])
    return [place for place in found if place is not None]


def _post(text: str, limit: int) -> dict:
    """Ask the geocoder for candidates and return its parsed body, or raise."""
    # POST with a form body rather than GET with a query string, so the API key
    # never appears in a request line — where it would reach proxy logs and
    # could surface inside an httpx exception's text. CLAUDE.md: secrets by
    # name, never by value, logs included.
    form = {
        "f": "json",
        "singleLine": text,
        "maxLocations": limit,
        # Nothing beyond the address, the point and the extent is used, and
        # asking for fields the portal ignores only widens what it handles.
        "outFields": "",
        # Explicit, so the service default cannot drift out from under the
        # SRID 4326 every other coordinate in the portal is in.
        "outSR": 4326,
        # The free tier. Storing results is what this flag governs, and stored
        # geocoding has no free allowance at all (docs/adr/011).
        "forStorage": "false",
        "token": settings.ESRI_API_KEY,
    }
    try:
        response = httpx.post(
            f"{settings.ESRI_GEOCODE_URL}/findAddressCandidates",
            data=form,
            timeout=settings.ESRI_TIMEOUT_SECONDS,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        # The exception type, not its message: an httpx message carries the URL
        # it was calling, and that URL is one refactor away from carrying the
        # key with it.
        raise EsriUnavailable(type(exc).__name__) from exc

    # The body is read before the status code on purpose, as in
    # apps/runs/dagster.py: the geocoder answers a rejected request -- an
    # expired token, say -- with HTTP 200 and an `error` object. That is the
    # geocoder answering, not the geocoder being down.
    try:
        payload = response.json()
    except ValueError:
        raise EsriUnavailable(f"HTTP {response.status_code} and no JSON") from None

    if "error" in payload:
        raise EsriError(payload["error"].get("message", "Unknown geocoding error"))
    if response.status_code >= 400:
        raise EsriUnavailable(f"HTTP {response.status_code}")
    return payload


def _place(candidate: dict) -> dict | None:
    """One candidate in portal terms, or None if it cannot be gone to."""
    location = candidate.get("location") or {}
    lon, lat = location.get("x"), location.get("y")
    # A candidate with no point is a row that would do nothing when picked, so
    # it is dropped rather than offered.
    if lon is None or lat is None:
        return None
    return {
        "name": candidate.get("address") or "",
        "lat": lat,
        "lon": lon,
        "bbox": _bbox(candidate.get("extent")),
    }


def _bbox(extent) -> list[float] | None:
    """An extent as [min_lon, min_lat, max_lon, max_lat], or None.

    None is a real answer: a place may come back with no extent, and one that
    crosses the antimeridian comes back inside-out. Neither half of an
    inside-out box is the place, so the portal reports no area rather than a
    box that means somewhere else. The point still works.
    """
    if not extent:
        return None
    corners = [extent.get(key) for key in ("xmin", "ymin", "xmax", "ymax")]
    if None in corners:
        return None
    if corners[0] > corners[2] or corners[1] > corners[3]:
        return None
    return corners
