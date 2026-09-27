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

Locally the knowledge base is the `geo_kb` database on the **same Postgres
instance** as `portal` — one instance, two databases, as docs/adr/002 describes.
Set `KB_DB_PORT` to that instance's port; a separate port means a separate
server and is wrong. A `minio` container stands in for the S3 buckets and must
be running for anything that reads the lake.

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
| `status` | `text` | default `active`; also `failed`, `superseded`, `missing` (the file is gone from storage) |
| `superseded_by` | `uuid` | supersession chain |
| `error` | `text` | |
| `run_id` | `uuid` | → `ingest_runs` |
| `ingested_at` | `timestamptz` | |
| `dataset` | `text` | **the dataset**: the top folder the file came from in the raw bucket, recomputed by the data platform on every run |

Indexes: GiST on `extent` (`assets_extent_gix`) and on `topic_path`; btree on
`(modality, status)`, `source_uri`, `dataset` (`assets_dataset_ix`), and the
two unique keys.

**`dataset` must exist in production before a portal build that reads it
ships.** The data platform added it on 2026-09-24 (gobase `411bc78`); the
portal reads it with no fallback, so the two repos deploy together
(docs/adr/016).

### How the spec's vocabulary maps onto this

- **"data type"** → `modality`. Read it from the database; never enumerate
  it in portal code.
- **"name"** → nothing. There is no name or title column. The portal derives
  one for the Assets page: the basename of `source_uri` with its extension
  removed, computed in SQL so display, search and sorting agree
  (docs/adr/010).
- **"coverage" / "footprint"** → `extent`. One column, SRID 4326, generic
  `GEOMETRY` so it may hold more than polygons.
- **asset UUID** (citations) → `asset_id`, a native `uuid`.
- **"dataset"** → `dataset`, shown as a readable label computed in SQL:
  `points_of_interest_hotsom` reads "Points of interest hotsom"
  (docs/adr/016). The folder names are the data's own, typos included.
- **"search"** → the catalog's text about an asset, built per request from
  `assets`, `geo_layers.columns` (names only) and `geo_raster_layers.tags`
  (values only) — see `_SEARCH_TEXT` in `apps/catalog/kb.py` and
  docs/adr/016.

### Query rules

- **Always filter `status = 'active'`.** Superseded and failed rows stay in the
  table. The `(modality, status)` index exists for exactly this pairing.
- Point-in-coverage uses the GiST index via
  `ST_Intersects(a.extent, ST_SetSRID(ST_MakePoint(%s, %s), 4326))`.
- Everything is SRID 4326. No reprojection is needed for GeoJSON output.
- Area filtering uses the same index via
  `ST_Intersects(extent, ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326))`
  — the catalog browse query's `bbox` parameter (docs/adr/011). It is the one
  place a bbox is an input rather than an output.
- **An extent can be invalid, and an invalid extent matches nothing.** A
  polygon whose vertices are all the same coordinate has zero area and
  `ST_IsValid` false, and `ST_Intersects` against it is false for *every*
  point — including its own coordinate. Nothing errors: point inspection just
  finds no assets anywhere, and a map asked to frame that extent zooms past
  the last basemap tile and shows an empty screen. `ST_IsValid(extent)` and
  `ST_Area(extent)` are the checks. The portal cannot fix it — `kb` is
  read-only (docs/adr/002) — so a bad extent is a data platform bug. This bit
  once, in September 2026; see the snapshots below. It is fixed, and the check
  is kept because it cost a session to diagnose the first time.

## `public.geo_layers` / `public.geo_raster_layers`

Per-layer detail hanging off an asset by `asset_id`, each with its own
`extent` (4326, GiST-indexed) and `layer_name`.

**A raw cursor gets `json` and `jsonb` as text.** Django sets psycopg 3 up
that way, because its own JSONField decodes them. So `columns`, `bands`,
`tags` and `stats` arrive as strings unless decoded, and until 2026-09-27
they reached the client as a line of JSON text. `kb._rows` now decodes every
JSON column by its type id (114, 3802), not by name.

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

Both end with the asset's `dataset` column.
- `v_inventory` — counts and bytes grouped by `topic_path, modality, format, status`.
- `v_gaps` — failed assets and layers carrying notes.

The two `v_queryable_*` views already encode the `status = 'active'` filter and
are the safer read surface where they fit.

## `public.ingest_runs`

One row per ingestion run: `run_id`, `started_at`, `finished_at`, `source`, and
counters `ingested` / `unchanged` / `superseded` / `failed`. Note this is the
*data platform's* own run bookkeeping — the Data Governance page reads
Dagster's GraphQL API instead (docs/adr/004), not this table.

## State of the local data

This section is a snapshot and goes stale; check it against the database
before trusting it. Earlier text is corrected rather than kept.

### Now — read 2026-09-27

**54 active assets** (89 rows: 12 superseded, 22 missing, 1 failed), across
three modalities:

| `modality` | active | with an extent |
|---|---|---|
| `vector` | 12 | 12 |
| `unparsed` | 31 | 0 |
| `raster` | 11 | 11 |

The 22 `missing` rows are the Dresden extract, trashed from silver on
2026-09-24; the 12 superseded are the Lebanon vector files rewritten that day
as GeoParquet 1.1. `geo_layers` still holds 35 rows, but only the 12 for
active assets are in `v_queryable_layers`.

**11 datasets**, and every active asset has one: `airports`, `boundaries`,
`education_facilities`, `esri_landcover_landuse`,
`google_microsoft_buildings`, `goverment`, `health_facilities`,
`healt_sites`, `main_cities_satellite`, `points_of_interest_hotsom`,
`road_network`. No dataset holds both raster and vector files; several hold
vector files beside `unparsed` documents.

**Every extent is valid.** `ST_IsValid` is true and `ST_Area` non-zero for
all 23 — the invalid zero-area polygons read on 2026-09-15 are gone, and the
point and area lookups both work against this data. That was a data platform
defect and it has been fixed there; nothing in this repo changed.

**`unparsed` is new**, and 31 of the 76 carry it. It has no extent and no
layer rows, so those assets cannot be found by clicking the map or by
filtering to an area — correctly, since the catalog holds no coverage for
them. The portal shows the type exactly as written and holds no list of
types, so this arrived without a code change, which is the point
(specs/map.md).

**`geo_raster_layers` is no longer empty**: 11 rows, one per raster asset.
`geo_layers` has 35.

Topics are real, with `.`-separated sub-paths below the dataset:
`airports.media`, `health_facilities.hotosm_lbn_health_facilities_osm_gpkg`.
Everything active is Lebanon.

A point in Beirut (`35.5, 33.89`) has 10 datasets under it, which makes it a
good place to try the map's panel.

### Two hand-made rows — read 2026-09-15, evening

**Superseded by the reading above; kept because the trap it describes is
real.** The catalog held two assets, `a.parquet` and `b.parquet`, whose
extents were `POLYGON((35.5 33.9, 35.5 33.9, ...))` — five identical
vertices, zero area, `ST_IsValid` false. Point inspection found nothing
anywhere, and it took a session to establish that the portal was right and
the data was wrong.

### The Dresden extract — read 2026-09-11

22 active assets (23 rows, one superseded or failed), **all
`modality = vector`**, all `topic_path = shapefiles_dresden` — an OpenStreetMap
extract of Dresden. `geo_layers` has one row per asset; `geo_raster_layers` is
empty, so there is **no raster asset at all**.

`geometry_type` spreads across `Point` (5), `Polygon` (6), `LineString` (1) and
`Mixed` (10), and `feature_count` runs from 3 to 10,068. Mixed geometry is
therefore the normal case, not an edge case, and a file above the server's
feature cap is reachable with real data.

`assets.source_uri` holds the full `s3://` URI of the GeoParquet, bucket
included — identical to `geo_layers.parquet_uri` for every active asset. It is
what the vector data endpoint reads.

**Three columns were empty across every active asset**, read 2026-09-15:
`summary`, `time_start` and `time_end`. They are in the API's responses as
nulls, and nothing renders from them yet. `summary` is the column a real
asset name would live in, so watch it: if the data platform starts
populating it, the derived name above becomes the fallback rather than the
source.

Every active asset also shares one `ingested_at` — the catalog was loaded in
a single run. Ordering by it therefore cannot separate the rows, which is why
the browse query breaks ties on `asset_id` (docs/adr/010).

`geo_layers.columns` lists the file's **attribute** columns only. The geometry
column is not in it, and one of the attributes is a text column called
`geomtype`, which a name guess would match by mistake. The geometry column name
must come from the file's own GeoParquet metadata.

What this data cannot exercise: **grouping across data types**, since every
asset is one modality, and **anything raster**.
