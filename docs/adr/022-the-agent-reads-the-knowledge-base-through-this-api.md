# ADR-022: The agent reads the knowledge base only through this backend's API

**Status:** Accepted · 2026-11-08

## Context

The 3 Nov plan gave the agent its own read-only `kb` role and its own
read-only lake keys, so that it could run free SQL. Its reason was that
"the user knows nothing about the data, so the agent must be able to ask
the data anything".

Hasan's v1 rules free SQL out, and group-by or statistics across
attributes too. What is left is nine fixed tools. Matched against this
backend on 2026-11-08, six of them map onto an endpoint that already
exists:

| Tool | Endpoint |
|---|---|
| `catalog_search` | `GET /api/catalog/assets` |
| `list_datasets` | `GET /api/catalog/datasets` |
| `describe_asset` | `GET /api/map/assets/{id}` |
| `find_place` | `GET /api/places/search` |
| `doc_search` | `GET /api/catalog/assets/similar` |
| `doc_passages` | `GET /api/catalog/passages` |

The other three fall short:

- **`vector_features`:** `/data` returns one page of features with no
  total and no filter.
- **`doc_read`:** `chunks.chunk()` reads one passage by id, but no endpoint
  serves it.
- **`raster_clip`:** nothing exists.

This backend's readers already hold the catalog's rules:

- active rows only;
- derived names and dataset labels (docs/adr/010, docs/adr/016);
- the two coverage modes (docs/adr/019);
- `ST_Intersects` for anything that counts;
- the embedder filter (docs/adr/018, docs/adr/020);
- pages counted from 1.

## Decision

- **Every agent tool is an HTTP GET to this backend.** The agent holds no
  `kb` role, no lake keys and no GoDoc address. This backend stays the one
  reader of the knowledge base for the portal, so the map and the chat give
  the same answer to the same question.
- **The backend gives the agent small answers.** It returns what a model
  can reason over: ids, names, columns, counts, a few sample rows,
  statistics. Features, pixels and PDFs reach the browser the way they do
  today, from the backend. The agent's answer carries only a reference to
  them (an asset id plus an area and a filter).
- **The backend adds four things:**
  - **A features summary:** the exact total inside an area, and a few rows
    of properties with no geometry.
  - **A simple attribute filter**, on the summary and on `/data` alike, so
    the map draws exactly what was counted. It takes a column the asset
    has, an operator from a fixed list (`equals`, `contains`, `in`, `<`,
    `>`), and a value bound as a parameter. It is not free SQL and not
    group-by.
  - **A passage by id:** its text, headings and pages.
  - **Raster statistics over an area:** per-band figures, plus each
    class's share named from the legend in the raster's tags. Also a clip
    download that the backend serves, reading only the window over the
    area from the COG.
- **The agent's credential is read-only.** Either an API key of a dedicated
  Viewer user, or a service token of its own. That choice is still open.
  API keys are on `dev` only, recorded in
  `021-desktop-clients-sign-in-with-an-api-key.md`, which shares this
  sequence's number 021 until the merge renumbers one of the two. Keys
  may only read.

## Rejected

- **The agent's own read-only access, with this backend's readers ported to
  it** (the 3 Nov plan). That means about 3,000 lines copied with their
  tests, and two copies of the catalog's rules to keep in step from then
  on. It also means two more holders of knowledge-base credentials. The
  three gaps above need building either way.
- **The agent importing this backend's modules.** They read Django's
  connection and settings, so it would pull Django into the agent and tie
  the two repos together.

## Consequences

- **Every new tool capability starts here**, as an endpoint in
  `openapi.yaml`. The agent pins itself to that contract.
- **`Week_12` must reach `dev` before the document tools work in a deployed
  portal.** `assets/similar`, `passages` and `pdf` exist only on `Week_12`.
- **Agent traffic comes back into this backend while it relays the
  agent's answer**, hence the async relay in docs/adr/021.
- **"Agent-issued SQL is SELECT-only" has nothing to guard in v1:** the
  agent issues no SQL. The rule stays for any later version that does.
- **Raster reading needs `rasterio` (GDAL) in the backend image.** The data
  platform's `gobase/cli/export_raster.py` has the windowed-read logic.

## Revisit when

- A later version of Ask needs free SQL or group-by. The choice then is a
  SQL endpoint here, or DuckDB access in the agent.
