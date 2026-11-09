# ADR-026: Place search picks its geocoder — Esri online, a local geocoder offline

**Status:** Accepted · 2026-11-08

## Context

`GET /api/places/search` turns typed text into places. Its geocoder is
Esri's. The key is held by this backend alone, and nothing is stored or
cached (docs/adr/011, context/integrations/esri.md). Esri needs the
internet.

The Ask agent has an offline mode for client sites without internet, and
client deliveries default to it (Hasan's requirements v0.4). One of its
nine tools, `find_place`, turns a place name into a point and a box. The
map's own search box has the same offline gap.

## Decision

- **The agent's `find_place` calls `GET /api/places/search`**, in both
  modes. It does not geocode on its own (docs/adr/024).
- **The backend chooses the geocoder by configuration:**
  - online, Esri, as today;
  - offline, a local geocoder. The pick is **Photon**, a light server
    over an OpenStreetMap extract (Lebanon alone is enough).
- **The contract does not change:** text in; up to `ESRI_MAX_CANDIDATES`
  results out, each a name, a point and a bbox. The map's search box and
  the agent get the same answer.

## Rejected

- **A separate gazetteer in the agent,** for example place names from the
  admin-boundary datasets in `kb`. There would be two place searches that
  can disagree about "Tripoli", and the map's search box would still have
  nothing offline.
- **The agent calling Esri itself.** That makes a second holder of the key
  and a second vendor client, and it still fails offline.

## Consequences

- **The geocoder becomes a setting,** with Esri and Photon each behind its
  own module, as `apps/places/esri.py` is today. How Photon is configured
  is decided when it is built, and a new integration doc goes in
  `context/integrations/`.
- **Until Photon exists, offline place search answers 503.** The agent's
  tool reports it as unavailable.
- **The Esri key stays in this backend alone.**
- **OpenStreetMap data has its own licence terms,** which Photon's
  integration doc must record. Esri's no-caching rule (docs/adr/011) does
  not apply to it.

## Revisit when

- The knowledge base gets a gazetteer dataset that names places better
  than OpenStreetMap does for this work.
