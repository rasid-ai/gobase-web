# ADR-010: The catalog is its own app, and its assets have a derived name

**Status:** Accepted · 2026-09-15

## Context

The Assets page browses everything the knowledge base holds. Two
questions had to be answered before it could be built, and both have
consequences beyond the page.

**Where the endpoint lives.** `apps/map` already serves three asset
URLs, and `GET /api/map/assets` already means *the assets covering this
point* — it requires `lon` and `lat`. A browse list is a different
question and cannot share that URL.

**What an asset is called.** The design assumes every asset has a name.
Read from the live catalog on 2026-09-15: `public.assets` has no name or
title column, `summary` is NULL for all 22 rows, and so are `time_start`
and `time_end`. The only human-readable string is `source_uri`, an
`s3://` path ending in a filename.

## Decision

**A new `apps/catalog`, serving `GET /api/catalog/assets`.** The module
that knows the knowledge base's tables moves there as `apps/catalog/kb.py`
and `apps/map` imports it. All three `/api/map/*` URLs are unchanged.

**An asset's name is derived: the basename of `source_uri` with its
extension removed.** `gis_osm_boundaries_07_1`. It is computed in SQL,
not in Python or in the client, because the same expression has to serve
three things at once — what is displayed, what `q` searches, and what
`sort=name` orders by. A name computed anywhere else would drift from
the one the database sorted on.

Consequences that follow, and are not optional:

- **`source_uri` does not appear in a browse row.** It carries the
  bucket path and the derived name replaces every use of it here. (The
  older at-point endpoint still returns it; that is pre-existing and out
  of scope.)
- **Text search cannot use an index.** `q` filters on a computed
  expression, so it scans. Twenty-two rows make that free; a large
  catalog needs a trigram index on the expression, and that is the
  moment to add one.
- **Every ordering ends in `asset_id`.** The whole live catalog was
  ingested in one run and shares a single `ingested_at`, so the default
  sort cannot tell its rows apart. Without the tiebreak, offset paging
  repeats some rows and silently drops others.
- **The type counts ignore the type filter.** Counts that collapse to
  the one type already selected say nothing about what else is there.

**Paging is by offset, not by cursor.** The Runs page pages by cursor
over a run id. This list sorts by four different columns and reports how
many assets match in total; a cursor over one id serves neither.

## Why

- Browsing the catalog is not a map feature. Putting it in `apps/map`
  would make that app the home of a page that has no map on it, and the
  URL would have to read `/api/map/catalog/assets`.
- `kb.py` already called itself "the only module that knows the
  knowledge base's tables and columns". That was true of one app and is
  now true of two, which is exactly why it should not live inside either
  of the readers.

## Rejected

**Ask the data platform repo for a name column first.** The honest fix —
names belong in the catalog, not derived by a reader. Rejected as a
blocker, not as an idea: it stops this page until another repo ships,
and the fallback would still have to exist for old rows. Worth raising
separately; if `summary` is ever populated it becomes the name and the
derivation becomes the fallback.

**Join `geo_layers.layer_name`.** It holds the same basename, already
extracted. Rejected because it exists only for vector assets — rasters
have their own table and a document has neither — so the name would be
present for some data types and missing for others.

**Keep the list in `apps/map`.** No app to create and no module to move.
Rejected for the reasons above; the import churn it avoided was two
lines.

## Revisit when

The catalog outgrows a scan on every text search, or the data platform
gives assets a real name. The first adds an index; the second turns the
derivation into a fallback rather than the source.
