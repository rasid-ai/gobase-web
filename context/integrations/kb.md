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
| `modality` | `text` | **the "data type" of specs/map.md** — `vector`, `raster`, `unparsed`, `document` |
| `format` | `text` | e.g. `cog`; for a document, the parser that read it (`mineru`). The portal shows a document's file format instead, `pdf` from `pdf_uri`, and keeps the parser in the detail as `parser` (docs/adr/017) |
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
  (docs/adr/010). A document is the exception: its `source_uri` is the
  parsed bundle, so it is named after `doc_documents.pdf_uri` instead,
  extension kept (docs/adr/017).
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

## `public.doc_documents` — the documents

One row per PDF the data platform parsed, beside its `assets` row
(`modality = 'document'`; `format` is the parser, `mineru` today). Added by
gobase on its `feature/godoc_document_integration` branch (2026-10-17); needs
the `vector` (pgvector) extension in `kb`.

| column | notes |
|---|---|
| `document_id`, `asset_id` | the row, and its `assets` row |
| `title` | what the parser read as the title — often missing, or a heading ("1. Introduction") |
| `headings` (`text[]`), `lang`, `pages` | |
| `bundle_uri` | the parsed bundle in silver, `…/documents/<tree>/<stem>.bundle.zip` — the same value as `assets.source_uri` |
| `pdf_uri` | **the PDF itself, in bronze**: `s3://geobase-bronze/raw/<tree>/<name>.pdf`. Null for a bundle loaded without its source stamp |
| `chunks_uri`, `chunker_id`, `embedder_id`, `dim`, `n_chunks` | the chunk table (one LanceDB table per embedder, on silver) and how it was built. The portal reads the table for deep search (context/integrations/lance.md, docs/adr/020); `embedder_id` is what it filters on, so a table made by another model is never searched with this question's vector |

Chunks are not in Postgres at all; `v_queryable_documents` is the
active-only view over the join. `doc.pages` and `doc.chunks_uri` ride on the
PDF read (`_DOCUMENT_PDF`) for the page image, which needs both.

**`doc_documents` must exist in production before this portal build ships.**
Every catalog read LEFT JOINs it (`_DOCUMENTS` in `apps/catalog/kb.py`), so
a `kb` without the table fails the Assets page outright — the same
deploy-together rule as `dataset`.

**`pdf_uri` can be stale.** When a PDF is moved in bronze the data platform
re-stamps the silver bundle but leaves `pdf_uri` until the next reindex, on
purpose. The PDF endpoint then answers 502. The bundle object's
`x-amz-meta-source-uri` is always current, if that ever matters.

What the portal makes of it (docs/adr/017): a document is named after
`pdf_uri`'s basename, extension kept; its bytes are served through
`/api/catalog/assets/{id}/pdf`; `assets.bytes` is always 0 for a document,
so the page shows `pages` instead; and `assets.content_hash` is the PDF's own
sha256, which is the endpoint's ETag.

### `public.doc_cards` — one embedding per document

| column | notes |
|---|---|
| `card_id`, `asset_id` | the card, and the `assets` row it describes |
| `embedder_id` | the model that made it — `BAAI/bge-small-en-v1.5` for every live card |
| `vector` | `vector` with **no fixed dimension**, because it varies by model (384 for bge-small). Unit length, so cosine (`<=>`) is the operator |

What was embedded is the card text — title, headings and the first words —
which is also what `assets.summary` holds for a document. One card per
(asset, model); in practice one per document. Indexes: only the primary key
and a btree on `asset_id`. **No ANN index**: a cosine search is a
sequential scan, which is fine at this size, and the data platform adds a
per-embedder partial index when the table earns it.

The portal's semantic search (`similar_assets` in `apps/catalog/kb.py`,
docs/adr/018) joins the browse CTE to the cards of one model — the one the
embedding service names for the question — and binds the query vector as
pgvector's text form, `'[0.1,0.2,…]'::vector`, so no pgvector adapter is
needed on the driver. It never names a modality: any asset with a card
comes back.

Beside each match it returns the dataset's extent, `ST_Extent` over the
dataset's active assets. **`airports` has no asset with an extent**, and
every live card is in `airports`, so that box is null for all of them
today.

## Views

- `v_queryable_layers` — `geo_layers` joined to active assets, `parquet_uri NOT NULL`.
- `v_queryable_rasters` — `geo_raster_layers` joined to active assets.
- `v_queryable_documents` — `doc_documents` joined to active assets.

All end with the asset's `dataset` column.
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

### Now — read 2026-10-19

The document chain has run locally (gobase on
`feature/godoc_document_integration`, unmerged; pgvector installed in
`geo_kb`). **4 `document` assets**, all in `airports`, `format = mineru`,
each with a `doc_documents` row whose `pdf_uri` points into
`geobase-bronze/raw/airports/`, and the PDF is there (1, 2, 8 and 4 pages;
the largest is 359 KB). Their old `unparsed`/`pdf` rows are `status =
'missing'` — the raw copies were trashed from silver once parsed — so the
browse list shows each PDF once.

Rows by modality: `vector` 47, `raster` 11, `document` 4, `unparsed` 31
(4 of those are the missing PDF copies). The titles are what the parser
found — "1. Introduction" for one, "TISO SOLUTIONS FOR SECURITY OF
AIRPORT:" for another — which is why the page names a document after its
file and shows the title second.

### Then — read 2026-09-27

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
