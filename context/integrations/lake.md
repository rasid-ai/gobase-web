# The lake — S3 object storage, read through DuckDB

The lake is where the row-level data lives. The knowledge base holds the
catalog and each asset's coverage; the features themselves are GeoParquet files
in an S3-compatible bucket, written by the data platform repo. The portal reads
them and never writes them.

Read on 2026-09-11 against MinIO and DuckDB 1.5.5.

## What talks to it

`backend/apps/map/lake.py`, and nothing else. It is the only module that
imports `duckdb`. Everything above it speaks GeoJSON.

DuckDB reads the lake only. It never touches Postgres — `kb` stays on Django's
connection and its read-only role (docs/adr/002).

## Configuration

Seven settings, all from the environment, all defaulted:

| setting | MinIO / RustFS | AWS S3 |
|---|---|---|
| `LAKE_S3_ENDPOINT` | `host:port` | blank — DuckDB uses AWS's own |
| `LAKE_S3_REGION` | blank — they have no regions | the bucket's real region |
| `LAKE_S3_URL_STYLE` | `path` | `vhost` |
| `LAKE_S3_USE_SSL` | `false` locally | `true` |
| `LAKE_S3_ACCESS_KEY` / `LAKE_S3_SECRET_KEY` | set | set, or **blank** |
| `LAKE_PAGE_SIZE` | 5000 | 5000 |

No provider is named anywhere in the code. Moving between RustFS and AWS is an
`.env` edit and a restart.

Blank credentials are meaningful, not missing: the secret is then created with
`PROVIDER credential_chain`, so DuckDB picks up an instance role. That is how
AWS is reached without static keys on the host.

Locally the bucket is the `minio` container on port 9000. It must be running
for anything that reads the lake; the catalog will happily hand out URIs to
objects nothing is serving.

## Two things that cost time to find

**Configure with `CREATE SECRET`, never `SET s3_*`.** This is the one that
costs real time. The legacy settings are session-scoped, and every request runs
on `connection.cursor()`, which opens its own session and does not inherit them
— so the store is reached with no configuration at all and answers **HTTP 404**,
which is indistinguishable from a missing file. A secret lives in the database,
so every cursor shares it. There is a regression test for this in
`apps/map/tests/test_lake.py`; the local-path tests cannot catch it, because a
local path needs no S3 configuration at all.

Note the error text in this case names an empty region, which is misleading.
The region is not the problem and MinIO ignores it entirely — verified against a
live MinIO, where `''`, `us-east-1` and `banana` all read the same file. The
empty region is just one visible consequence of no configuration arriving.

**The geometry column name comes from the file, not from a guess.** GeoParquet
records it in the file's `geo` metadata key. The catalog's `geo_layers.columns`
lists attribute columns only and does not include it — and it does contain a
text attribute called `geomtype`, which a name-matching heuristic hits by
mistake (context/integrations/kb.md).

## Reading

`read_vector_features(uri, limit=, bbox=, cursor=)` runs one query. Both
filters are optional; with neither, the whole file is in scope:

```sql
SELECT ST_AsGeoJSON(<geometry>) AS __geometry__,
       file_row_number          AS __cursor__,
       * EXCLUDE (<geometry>, file_row_number)
FROM   read_parquet(?, file_row_number = true)
WHERE  bbox.xmin <= ? AND bbox.xmax >= ?                        -- with bbox, if
   AND  bbox.ymin <= ? AND bbox.ymax >= ?                        -- the file has one
   AND  ST_Intersects_Extent(<geometry>, ST_MakeEnvelope(?, ?, ?, ?))  -- with bbox
  AND  file_row_number > ?                                      -- with cursor
ORDER BY file_row_number
LIMIT  <limit + 1>
```

Both filters are pushed into the scan, so a file is never fully materialised to
return the part of it the map can see. It asks for one row beyond the page,
which is what distinguishes a page that exactly fills `limit` from one with
more behind it; the last kept row's `file_row_number` is the `next_cursor`.

**Paging is keyset, never offset.** `read_parquet` has no inherent order and
DuckDB scans in parallel, so an offset would repeat some rows and skip others
between pages. `ORDER BY file_row_number` makes the sequence stable, and
`file_row_number > ?` makes the next page a range scan: a later page costs no
more than the first (measured flat at ~25-35ms over 200k features), because
DuckDB stops as soon as it has enough rows rather than reading and skipping.

**The area filter matches bounding boxes, not exact geometry.**
`ST_Intersects_Extent` is a box-against-box test. It is over-inclusive and
never under-inclusive: a feature whose box overlaps the area but whose geometry
does not comes back as well. Free for drawing — it lands off screen — but
anything that counts or answers from this endpoint has to know.

## The covering bbox column

Silver writes a `bbox STRUCT(xmin, ymin, xmax, ymax)` column beside the
geometry — one box per feature, the GeoParquet 1.1 "covering" column — with
rows in Hilbert order and row groups of 25,000. `bbox` is not the file's data.
It is derived from the geometry, it exists for readers to prune with, and it is
excluded from the properties so it never reaches the map.

**The query has to name it.** DuckDB 1.5.5 does not derive a range test from
`ST_Intersects` or `ST_Intersects_Extent`, so without the explicit
`bbox.xmin <= ? AND …` condition the covering column buys nothing and every row
of the file is read off the object store to answer any area query. With it,
DuckDB checks each row group's min/max statistics and skips the groups that
miss, before reading any geometry.

`gobase/cli/export.py` — `is_covering_bbox()` and `bbox_filter()` — is the
other half of this agreement. Both repos hardcode the name `bbox` and the
`STRUCT(XMIN…` type test; they must not drift.

**A file without the column still reads**, it just reads all of itself to
answer an area query. That is a defect in what wrote the file, not a failure to
raise, so the reader logs a warning once per URI and carries on. Breaking the
map over it would be worse than the thing being reported. As of the 2026-09-24
silver rewrite all 12 active vector assets carry the column, so the warning
firing at all means something upstream has regressed.

Measured through `read_vector_features` over a million features, same rows
either way:

| window | no covering column | with it |
| --- | --- | --- |
| a city | 392 ms | 71 ms |
| a street | 300 ms | 22 ms |

The exact `ST_Intersects` predicate was also measured, at 18-40% slower than
`ST_Intersects_Extent` for identical rows on the real layers, which is why the
extent test is the one in the query. Reading `lebanon_buildings_full.parquet`
whole is 27 s, which is what the area filter is for (docs/adr/013).

**The geometry column reads back as `GEOMETRY`, not `BLOB`.** DuckDB's spatial
extension types it from the file's `geo` metadata, which is why `ST_Intersects`
and `ST_AsGeoJSON` take it directly. A Parquet file holding WKB *without* that
metadata comes back as `BLOB`, and there is no `BLOB -> GEOMETRY` cast — it
would need `ST_GeomFromWKB`. `parquet_schema` reports `BYTE_ARRAY` for both, so
it cannot tell them apart; `typeof()` on a read can.

Every non-geometry column becomes a GeoJSON `properties` key. Types are not
known ahead of time — the columns differ per file — so values JSON cannot hold
(timestamps, decimals, UUIDs) are coerced to strings.

## Failures

Two exceptions, and the distinction matters because it decides the status code:

- `LakeUnavailable` → **503**. The lake could not be reached, or refused the
  credentials. Try again later; the file is not the problem.
- `LakeReadError` → **502**. The lake answered and the object is missing or is
  not readable as GeoParquet.

DuckDB reports both as `IOException`, so the message is the only thing telling
them apart — `_UNAVAILABLE_MARKERS` in `lake.py` holds the substrings. That list
is a heuristic and will need extending when DuckDB rewords something. A new
DuckDB version is the thing most likely to break this.

The `CREATE SECRET` statement carries the secret key, so its failures are
reported by exception type only and never by message.
