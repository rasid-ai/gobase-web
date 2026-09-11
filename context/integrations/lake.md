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
| `LAKE_MAX_FEATURES` | 5000 | 5000 |

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

`read_vector_asset(uri, limit)` runs one query:

```sql
SELECT ST_AsGeoJSON(<geometry>) AS __geometry__, * EXCLUDE (<geometry>)
FROM read_parquet(?) LIMIT <limit + 1>
```

The cap is pushed into the scan, so a 10,000-feature file is never fully
materialised to return 5,000 of them. It asks for one row beyond the cap, which
is what distinguishes a file of exactly `limit` features from a truncated one.

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
