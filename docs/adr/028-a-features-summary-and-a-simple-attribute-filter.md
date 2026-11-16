# ADR-028: A features summary for answers, and a simple attribute filter

**Status:** Accepted · 2026-11-10
**Builds on:** docs/adr/024 (the agent reads through this API), docs/adr/012
and docs/adr/014 (windows and drawn areas), docs/adr/015 (the features
endpoint's ETag)

## Context

ADR-024 decided that the Ask agent's `vector_features` tool gets two things
from this backend: an exact count of an asset's features in a place with a
few sample rows, and a simple attribute filter that the count and the map's
layer both take. It left the details open.

`GET /api/map/assets/{id}/data` is built for drawing. Its `count` is the
page's count, not the total. A drawn area is tested exactly, but a bbox is
tested box against box (`ST_Intersects_Extent`), which is cheap and lets in
features whose bounding box overlaps the window while their shape does not
(docs/adr/012). That is free for a map and wrong for a figure in an answer.
It also returns whole features, which are too heavy to hand a model.

## Decision

### `GET /api/map/assets/{asset_id}/summary`

For an active vector asset it answers `{asset_id, total, sample}`.

- **Parameters:** `bbox` or `area` (not both; neither counts the whole
  file), the filter below, and `sample` (0–10 rows, default 5).
- **`total` is exact, for a bbox too.** A bbox is tested with
  `ST_Intersects` against the rectangle, on the real geometry. The covering
  column still prunes first (docs/adr/013), so the exact test only runs on
  what the rectangle's box let through.
- **`sample`** is the properties of the first matching features in file
  order. No geometry, no covering `bbox`, NaN as `null`: the same rules as a
  page's properties.
- **Failures** as for `/data`: 404 for anything but an active vector, 400
  for a bad parameter, 502 and 503 from the lake.
- **A plain DRF response.** The body is small, so it has no gzip and no ETag.
- The count and the sample are two queries over the same conditions. One
  query would build every matching row's properties to keep five.

### The attribute filter, on `/summary` and `/data` alike

Three query parameters, all or none: `filter_column`, `filter_op`,
`filter_value`. `filter_value` is repeated to give `in` several values.

- **The column** must be an attribute column of the file. The geometry, the
  covering `bbox` and `file_row_number` are not. An unknown column is a 400
  whose message lists the real columns, so the agent's next call can be
  right. The name is compared with the file's own column names and then
  quoted; it is never pasted into SQL.
- **The operator** is one of `equals`, `contains`, `in`, `<`, `>`: the
  strings the chat reference already uses (context/integrations/agent.md).
- **Every value is a bound parameter.** No SQL comes from the caller.
- **`equals` and `in`:** text is compared without regard to case. Any other
  type is compared by value, after casting the value to the column's type.
- **`contains`:** text columns only, without regard to case. `%` and `_` in
  the value are ordinary characters.
- **`<` and `>`:** numbers, dates and timestamps only.
- **Nulls never match.** NaN never matches `<` or `>` either (DuckDB sorts
  it above every number).
- **Numbers are compared as numbers.** `1.5` against a whole-number column
  means 1.5; it is not rounded to 2 by a cast to the column's type.
- **A whole-number column is compared exactly.** For `equals` and `in`, each
  value is compared in the column's own type, one value at a time, so a
  64-bit id never passes through a DOUBLE. A value no whole number can equal
  (`1.5`, or a number too large for the column) matches nothing and is left
  out. `7.0` means 7.
- **A 32-bit FLOAT column is compared as FLOAT.** Its 0.1 is not the DOUBLE
  0.1, so the value is cast to the column's type, not the column widened.
- **Timestamps:** a zone offset in a value is ignored for a column with no
  zone (`TIMESTAMP`), and a value with no zone is read in the server's zone
  for a column with one (`TIMESTAMP WITH TIME ZONE`). This is DuckDB's own
  cast.
- **Infinity and NaN are not values a filter takes** (a 400). `> 0` still
  matches a row holding infinity.
- **Refused with a 400** that names the parameter at fault: an operator the
  column's type does not allow, a value that is not of the column's type,
  more than one value for anything but `in`, more than 20 values, a value
  over 200 characters, a nested or binary column (STRUCT, LIST, MAP, BLOB).
- **Text types** are VARCHAR, UUID and ENUM.

### `/data` keeps its unfiltered ETags

The ETag of a filtered page includes the filter. The ETag of an unfiltered
page is computed exactly as before, so `FEATURES_FORMAT` stays at 1 and no
browser refetches a page it already holds. A test pins the old value.

## Rejected

- **Case-sensitive `equals`.** The caller is a model that has seen a column
  name and perhaps a sample value. `amenity = School` finding nothing where
  `school` finds 2,000 reads as "there are none", which is a wrong answer
  rather than an error.
- **Counting a bbox by boxes**, as `/data` reads one. Cheaper, and an
  over-count that the answer would state as fact.
- **Free SQL, or a WHERE fragment.** Hasan's v1 rules it out, and it would
  make the "SELECT-only" guard real work (docs/adr/024).
- **Several filters, AND/OR, group-by.** Not in v1. The agent counts each
  value with its own call.
- **Making `/data` exact for a bbox when a filter is sent.** It would make
  one parameter change the meaning of another. A client that must draw
  exactly what a rectangle counted sends the rectangle as an `area`.
- **Bumping `FEATURES_FORMAT`.** Not needed: no existing request's body
  changed.

## Consequences

- **A bbox count and a bbox layer can differ** for lines and polygons: the
  layer may draw a few features whose box touches the window. Seen on the
  local roads: 202 counted in a small window, 203 drawn. An `area` is exact
  on both. Points are the same on both. A test pins the difference.
- **The Ask agent never sends a bbox here.** It sends every rectangle (the
  map view, a found place's box) as a rectangle `area`, and its `layer`
  reference carries that `area` (gobase-agent docs/adr/011). So `/data` with
  the reference's `area` and filter returns exactly the features counted.
- **`lower()` on a column cannot use Parquet statistics**, so a text filter
  reads the column for every row the place let through. Measured locally
  on 2026-11-10: a text filter over all of `points_of_interest` (18,477
  rows) took 70–110 ms, an unfiltered count of the buildings in a Beirut
  window (24,982 of them) 170 ms, and a whole-file count of the roads
  (148,925) 50 ms.
- **The filter's 400 quotes the caller's value and the file's column names.**
  Both are data the caller may already read through `/data`. It never names
  the lake path.
- **`filter_column` is matched exactly**, case included. The message lists
  the columns, which is what tells a caller the right spelling.
- **The frontend does not send a filter yet.** An answer's layer is still
  drawn for the current area or view (specs/map.md, "Answer layers"). The
  generated client has the parameters.

## Revisit when

- An answer's layer is drawn with its own area and filter. The reference
  already carries an `area` for every place, so nothing here changes.
- A later version of Ask needs several conditions or group-by (ADR-024's
  own "revisit").
- Text filters on a very large file are slow: an exact-case first pass
  could use the file's statistics.
