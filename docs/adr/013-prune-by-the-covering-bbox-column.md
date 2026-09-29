# ADR-013: The area filter prunes by the covering bbox column

**Status:** Accepted · 2026-09-24

Retires the ceiling recorded in ADR-012. That ADR said every window is a
full scan of the file, called it "the ceiling on the approach", and opened
a "Revisit now, not later" section saying the way out was bbox covering
columns written by the data platform. That work has been done. This ADR is
the reader half of it. ADR-012 is not edited; its measurements were true of
the files that existed then.

## Context

`read_vector_features` filtered an area with `ST_Intersects_Extent` alone.
DuckDB cannot use that to skip any part of a file, so every map request
downloaded the whole thing. Measured over S3 on the buildings layer
(1,012,407 features) with DuckDB's cache off: 89.4 MiB and 1.9 s per
request — per visible layer, per pan.

The data platform now writes silver GeoParquet with a `bbox
STRUCT(xmin, ymin, xmax, ymax)` column beside the geometry — one box per
feature, the GeoParquet 1.1 "covering" column — rows in Hilbert order so
that features near each other on the map sit near each other in the file,
and row groups of 25,000 with zstd.

None of that helps on its own. **DuckDB 1.5.5 does not derive a range test
on the covering column from `ST_Intersects` or `ST_Intersects_Extent`.**
Checked on both sides. The query has to name the column.

## Decision

**When the file has a covering column and an area was asked for, test it
first.**

```sql
bbox.xmin <= ?  AND bbox.xmax >= ?
AND bbox.ymin <= ?  AND bbox.ymax >= ?
AND ST_Intersects_Extent(<geometry>, ST_MakeEnvelope(?, ?, ?, ?))
```

DuckDB checks the range test against each row group's min/max statistics
and skips the groups that miss, before reading any geometry. The extent
test then runs on what survived, and still decides the answer — the range
test only removes row groups that could not have matched.

- **Detected by name and type, not from the `geo` metadata's `covering`
  key.** `gobase/cli/export.py:is_covering_bbox` tests exactly this, and
  the two halves must agree. It also matches a file DuckDB itself wrote:
  `COPY` emits the column but not that metadata, so a metadata check would
  miss files the range test would work perfectly well on.
- **`bbox` is excluded from the properties.** It is derived from the
  geometry and exists to filter with, so it is not the file's data. Without
  the exclusion every feature on the map carries a `bbox` field nobody put
  in the file.
- **A file without the column still reads.** It reads all of itself to
  answer an area query, which is what happened before this change, so
  nothing regresses. The reader logs one warning per URI and carries on.

## Rejected

**Requiring the column, and failing the read without it.** Every silver
file is supposed to have one, so in principle a file without it is a
defect and should be loud. Rejected because it is loud in the wrong place:
the map would go blank for an asset that reads perfectly well, and the
person who sees it cannot fix the file. A warning names the file and the
map keeps working. Right now this is not hypothetical — **0 of 34 active
vector assets carry the column**, because local silver has not been
rewritten yet.

**Detecting via the `geo` metadata `covering` key.** Stricter, and it is
the spec's own answer. Rejected because it would not match a file written
by DuckDB's `COPY`, which is what the tests write, and because it puts the
two repos' detection rules out of step for no gain — a `bbox` column of
type `STRUCT(XMIN…)` beside a geometry is a covering column whatever the
metadata says.

## Consequences accepted

- **Both repos hardcode the column name `bbox`.** It is a contract with no
  schema behind it. If the data platform renames it, the portal silently
  stops pruning and gets slow rather than wrong — which is the failure
  mode to prefer, but it is silent apart from the warning.
- **One extra `DESCRIBE` per read**, on top of the metadata reads
  `_geometry_column` already does. It reads the footer only.
- **The over-inclusive filter is unchanged.** `ST_Intersects_Extent` still
  matches bounding boxes rather than exact geometry, and the range test is
  a bounding-box test too, so the endpoint's contract is the same: a
  feature whose box overlaps the area but whose geometry does not comes
  back. Free for drawing; anything counting from it has to know.

## Measured

Through `read_vector_features`, a million features, identical rows both
ways:

| window | no covering column | with it |
| --- | --- | --- |
| a city | 392 ms | 71 ms |
| a street | 300 ms | 22 ms |

The three parts of the change were isolated, because a first reading of
these numbers credited the wrong one. Same million rows, one variable at a
time, `threads=1` to take parallelism out of it:

| file | query | ms |
| --- | --- | --- |
| one row group | extent only | 259 |
| 25k row groups, sorted, no bbox | extent only | 254 |
| 25k row groups, shuffled, bbox | range + extent | 308 |
| 25k row groups, sorted, bbox | range + extent | **33** |

**Row groups alone skip nothing.** 259 ms to 254 ms. At default threads the
same file looks 7x faster, but that is DuckDB scanning row groups in
parallel — a local effect that saves no bytes, which is why the handoff
still measured 89.4 MiB downloaded per request.

**The range predicate is the only thing that reads less**, and it only
works because the rows are ordered. Counting row groups whose own bbox
statistics overlap a Beirut window: 4 of 38 on the sorted file, 38 of 38 on
the shuffled one. Hilbert order is what puts a window's features into a few
adjacent groups instead of smearing them across all of them.

So none of the three is redundant and none is sufficient: the column
carries the statistics, the ordering makes them selective, the predicate is
what asks. Drop any one and the file is read whole.

## Revisit when

`PAGE_BUDGET` in `useAssetFeatures.ts` was set to 2 against the old costs,
and the open question of dropping it to 1 was argued from a ~1.9 s second
page. That argument is gone once silver is rewritten. Re-decide it then,
with a browser open, rather than carrying a number tuned for a file layout
that no longer exists.

Vector tiles (ADR-003) remain the answer if a single window ever holds
more than a page. This change makes that further away, not nearer.
