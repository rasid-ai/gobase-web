# ADR-016: Datasets, metadata search, and one catalog API for both pages

**Status:** Accepted · 2026-09-27
**Supersedes in part:** docs/adr/010 (the map's `/api/map/assets` as a
separate question from browsing), docs/adr/014 (a drawn area asked through
`/api/map/assets`)

## Context

Search on the Assets page matched the derived file name and nothing else, and
the map's panel had no search at all. The catalog holds far more text than a
file name: the names of a vector file's columns, a raster's tags (its year,
its source, its land-cover classes), topics and formats. None of it could be
searched.

On 2026-09-24 the data platform added `assets.dataset`: the top folder a file
came from in the raw bucket, recomputed on every run (gobase `411bc78`).
Locally there are 11, and every active asset has one. People think in these
groups — "the boundaries", "the land-cover rasters" — and neither page could
show them.

Both pages wanted the same new abilities: list the datasets, open one, search
its files, and choose by data type. The Assets page asks this of the whole
catalog or of a searched place; the map's panel asks it of a clicked point or
a drawn area. Until now the two pages used two endpoints — the catalog browse
for one, `/api/map/assets` for the other — which had already drifted: the
map's answer was grouped by data type, unpaged, and had no name field.

## Decision

### One catalog API answers both pages

- `GET /api/catalog/assets` takes a **place**: a searched place's `bbox`, a
  clicked point's `lon` and `lat`, or a drawn `area` — at most one. It also
  takes `dataset`, an exact value.
- `GET /api/catalog/datasets` is new. It lists the datasets holding at least
  one matching asset, each with its readable label, its count, and its counts
  per data type. It takes the same place and ingestion window.
- `GET /api/map/assets` is **removed**. The map's panel calls the two above.

Every read comes off one query — the browse CTE, with the place inside it — so
a dataset's count is exactly the number of assets found on opening it, and the
page, the total and the counts cannot disagree.

### Search is over the catalog's text, as one literal piece

`q` on the asset list matches the asset's **search text**: its file name,
dataset and dataset label, topic, format, data type, summary, each layer's
name, the column names of a vector layer, and the tag values of a raster one.

- **Exact match.** What was typed must appear, as typed, inside one field.
  Case does not matter. No splitting into words, no fuzzy matching.
- **Fields cannot run together.** They are joined with the unit separator, a
  character nobody types, and that character is removed from what is typed.
- **Values, never whole JSON documents.** Column names and tag values are
  pulled out with the database's JSON functions. Casting a document to text
  would make `name` and `dtype` match every vector asset.
- **Tag keys are left out.** Every raster has a `year`; matching keys would
  make "year" find all of them.

`q` on the dataset list matches the dataset's name or its label only — never
its files. Searching datasets and searching files are two questions, and each
level of the interface asks one.

### A dataset has a readable label, made in SQL

`points_of_interest_hotsom` becomes "Points of interest hotsom": camelCase is
split, underscores and hyphens become spaces, and the result is in sentence
case. It is computed in the query, not in the interface, so a search matches
the words on the screen. The data's own spelling stays — the knowledge base is
read-only, so `goverment` is "Goverment".

### The interface browses in levels

- **Assets page:** two modes. *Datasets* lists the datasets, searched by
  name; opening one lists its assets, searched by metadata and filtered by
  data type. *Assets* is the flat list, searched by metadata.
- **Map panel:** the datasets at the point or area, then the files of one
  with a data type choice, then a file's detail.
- **The data type choice appears only once a dataset is open.** A dataset
  holds several types, so choosing one among datasets means nothing.
- **The detail expands.** Collapsed, it shows plain values. Expanded, it
  widens and shows every structured value — `columns`, `bands`, `tags`,
  `stats` — as a table. Decided by the value's shape, never by its key.

## Measured

Local catalog, 54 active assets, through the views:

| request | time |
|---|---|
| search text built and matched for every asset | 1.5 ms in SQL |
| datasets at a point in Beirut | 14 ms |
| datasets with a search | 4 ms |
| assets matching `water` (7 rasters by tag, 2 vectors) | 13 ms |

## Rejected

**Searching in the browser.** The panel's list is small enough to filter
client-side, but the metadata it would need — column names, tags — is not in
the list, and the portal's rule is that the client renders answers rather than
computing them (docs/adr/011, context/ui-rules.md).

**Keeping `/api/map/assets` and adding the same filters to it.** Two endpoints
asking one question drift apart, and these two already had.

**Casting the layer rows to text and matching that.** One line of SQL, but it
matches JSON keys and punctuation, and a search would find what the catalog
does not say.

**A stored, indexed search column.** Fast at any size, but it is a column in
`kb`, which the portal cannot write (docs/adr/002). Unneeded at this size.

**Word-by-word or fuzzy search.** Asked for as a later step, not now.

## Consequences accepted

- **Production must have `assets.dataset` before this ships.** The two repos
  deploy together; there is no fallback for a missing column.
- **The search text is built on every request.** Cheap at 54 assets. At tens
  of thousands it will need a stored search column, which the data platform
  would own.
- **An asset whose `dataset` is null is in no dataset.** It still appears in
  the flat list and on the map through search, but not under a dataset. The
  data platform labels every active asset on every run, so a null is a gap
  between two of its steps.
- **The mode and the open dataset are not in the URL.** By ADR-011's rule,
  a parameter exists only for state that crosses pages. The browser's Back
  button leaves the Assets page rather than stepping out of a dataset.

## Revisit when

Searches need to match words in any order or tolerate typos; the catalog
grows past a few thousand active assets; or a dataset needs to cross between
pages, which would give it a URL parameter.
