# Knowledge base (`kb`) — schema and access

The knowledge base is owned by the data platform repo. This portal **reads it
and never writes it** (docs/adr/002). Everything here was read from a live
instance; treat the data platform repo as the authority if the two disagree.

Read on 2026-09-08 from PostgreSQL 16.4 / PostGIS 3.4.3.

## Connecting

Django holds `kb` as a second alias in `DATABASES`, configured from
`KB_DB_NAME`, `KB_DB_USER`, `KB_DB_PASSWORD`, `KB_DB_HOST`, `KB_DB_PORT`.
`config/db_router.py` refuses writes and migrations against the alias, and
production additionally enforces read-only through the `portal_kb_reader` role
(infra/README.md).

Locally the knowledge base is the `gobase-test-pg` container
(`postgis/postgis:16-3.4`), serving database `geo_kb` on port 5433. A `minio`
container alongside it stands in for the S3 buckets.

`DATABASES["kb"]["TEST"]` is `{"MIRROR": "default"}`, so **tests never get a real
`kb`**. Code that reads the knowledge base must be fakeable at its own boundary.

## Extensions

`postgis 3.4.3`, `postgis_topology`, `postgis_tiger_geocoder`, `fuzzystrmatch`,
`ltree`. The `tiger` and `topology` schemas are PostGIS boilerplate and hold no
project data. **There is no H3 extension** — coverage is PostGIS geometry, not
H3 cells.

## `public.assets` — the catalog

One row per ingested asset. This is the table the portal's Map and citation
features resolve against.

| column | type | notes |
|---|---|---|
| `asset_id` | `uuid` | primary key — the UUID citations reference |
| `content_hash` | `text` | unique; the deduplication key |
| `source_uri` | `text` | where it came from |
| `topic_path` | `ltree` | hierarchical topic, e.g. `imagery` |
| `modality` | `text` | **the "data type" of specs/map.md** — e.g. `raster` |
| `format` | `text` | e.g. `cog` |
| `sidecars` | `text[]` | |
| `bytes` | `bigint` | |
| `extent` | `geometry(GEOMETRY, 4326)` | **coverage / footprint** |
| `time_start`, `time_end` | `timestamptz` | temporal extent |
| `summary` | `text` | |
| `status` | `text` | default `active`; also `failed` |
| `superseded_by` | `uuid` | supersession chain |
| `error` | `text` | |
| `run_id` | `uuid` | → `ingest_runs` |
| `ingested_at` | `timestamptz` | |

Indexes: GiST on `extent` (`assets_extent_gix`) and on `topic_path`; btree on
`(modality, status)`, `source_uri`, and the two unique keys.

### How the spec's vocabulary maps onto this

- **"data type"** → `modality`. Read it from the database; never enumerate
  it in portal code.
- **"coverage" / "footprint"** → `extent`. One column, SRID 4326, generic
  `GEOMETRY` so it may hold more than polygons.
- **asset UUID** (citations) → `asset_id`, a native `uuid`.

### Query rules

- **Always filter `status = 'active'`.** Superseded and failed rows stay in the
  table. The `(modality, status)` index exists for exactly this pairing.
- Point-in-coverage uses the GiST index via
  `ST_Intersects(a.extent, ST_SetSRID(ST_MakePoint(%s, %s), 4326))`.
- Everything is SRID 4326. No reprojection is needed for GeoJSON output.

## `public.geo_layers` / `public.geo_raster_layers`

Per-layer detail hanging off an asset by `asset_id`, each with its own
`extent` (4326, GiST-indexed) and `layer_name`.

`geo_layers` (vector) carries `geometry_type`, `native_crs`, `feature_count`,
`columns` (jsonb), `parquet_uri`. `geo_raster_layers` carries raster properties —
`width`, `height`, `band_count`, `dtype`, pixel sizes, `nodata`, `is_cog`,
`overview_count`/`overview_factors`, plus `bands`, `tags` and `stats` as jsonb.

**These jsonb columns are where the dynamic metadata comes from.**
The field set genuinely differs by modality, which is why the spec refuses to
pin one.

## Views

- `v_queryable_layers` — `geo_layers` joined to active assets, `parquet_uri NOT NULL`.
- `v_queryable_rasters` — `geo_raster_layers` joined to active assets.
- `v_inventory` — counts and bytes grouped by `topic_path, modality, format, status`.
- `v_gaps` — failed assets and layers carrying notes.

The two `v_queryable_*` views already encode the `status = 'active'` filter and
are the safer read surface where they fit.

## `public.ingest_runs`

One row per ingestion run: `run_id`, `started_at`, `finished_at`, `source`, and
counters `ingested` / `unchanged` / `superseded` / `failed`. Note this is the
*data platform's* own run bookkeeping — the Runs page reads Dagster's GraphQL
API instead (docs/adr/004), not this table.

## State of the local fixture data

Three assets, all `modality = raster`, `format = cog`, `topic_path = imagery`,
`status = active`, sharing one small polygon extent near 33.00°E 33.54°N.
`geo_raster_layers` holds three matching rows; `geo_layers` is empty, so there
is no vector asset at all.

So asset detail already returns rich dynamic metadata for rasters — `band_count`,
`bands`, `dtype`, `is_cog`, `width`/`height`, pixel sizes, `stats`, `tags`. What
the fixture data cannot exercise is **grouping across data types**: every asset
is the same modality, so a single group is the only outcome reachable against
real data.
