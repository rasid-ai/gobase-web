# ADR-019: The Assets page searches one thing at a time, and finds a place by its datasets

**Status:** Accepted · 2026-10-26
**Builds on:** docs/adr/011 (the area as `?place=&bbox=`), docs/adr/016 (one
catalog API for both pages)

## Context

The Assets page had one search box doing two jobs. What was typed filtered the
catalog by metadata straight away, and the same text was offered to the
geocoder as places. Picking a place set the area and left the text in place.

In use this proved bad:

- **A place emptied the list.** To find Beirut you type "Beirut", which also
  searches names for "Beirut". Picking the place kept that text, so the page
  asked for names containing "Beirut" inside Beirut, and found nothing.
- **Nothing said which filter was which.** The box and the area chip both read
  "Beirut". Switching modes cleared the text but kept the area, and the page
  looked as if a removed filter were still shown.
- **Every metadata search was billed as a place search.** `shapeName` and
  `gis_osm` went to the geocoder too.
- **A place hid most of the catalog.** The area matched each asset's own
  coverage. 31 of 54 active assets have none (all documents and unparsed
  files), so any area dropped them, even when their dataset was in the place.

Semantic search is coming to this page as a third kind of search.

## Decision

### One kind of search at a time, chosen beside the box

A small switch under the box chooses **Metadata** or **Places**: two icons,
quieter than the Datasets / Assets switch, because they change only what the
box is for. **Semantic** will be the third.

- **Metadata** filters as it is typed (dataset names among datasets, asset
  metadata elsewhere) and never reaches the geocoder.
- **Places** sends what is typed to the geocoder only and filters nothing.
  Picking a place sets the area and empties the box.

The filters combine. Each one the box set is shown under it as a chip named
by its kind (Place, or Metadata while the box is finding places), so the two
cannot be mistaken for each other.

### Switching between Datasets and Assets clears every filter

The search, the data types, the date and the area all go, so nothing stays
applied that the rail no longer shows. The sort stays, because it orders and
does not filter.

### A place is matched by the datasets' coverage

The catalog endpoints take `coverage`: `asset` (the default, each asset's own
coverage) or `dataset`. With `dataset`, an asset matches when any active asset
of its dataset overlaps the place. A dataset in the place therefore brings
every one of its files, those with no coverage included. An asset with no
dataset is matched by its own coverage.

The Assets page sends `coverage=dataset` in both modes. The map does not: its
question is what covers this point, which is a question about each asset.

A dataset's coverage is the **union** of its assets' coverage, tested as "any
asset overlaps". It is not the box around them: the box around two far-apart
files covers everything between them. The test is one `IN` subquery that uses
the GiST index on `extent`. The place appears twice in the SQL, so it is
bound twice.

## Rejected

**Keeping one box and guessing what the text means.** "Beirut" is a place and
a word in file names. No rule can tell which was meant, and guessing wrong
hides results.

**Changing what `bbox` means instead of adding `coverage`.** Only the Assets
page sends `bbox` today. But a place would then follow two rules depending on
its shape, and nothing in the URL would say which.

**The box around the dataset's assets (`ST_Extent`).** This is what the
Semantic results show as `dataset_bbox`, to frame the map. As a filter it is
too wide, for the reason above.

**Keeping the area when switching modes.** It describes where rather than
what, and the spec kept it for that reason. But a filter that outlives the
switch while the others go is the confusion this decision removes.

## Consequences accepted

- **A dataset with no coverage at all is in no place.** Today that is
  `airports`, whose files are all documents and unparsed. It needs one file
  with an extent, or a footprint the data platform would add.
- **An area from a map link is cleared by switching modes.** Following a link
  lands in Datasets mode with the area set; switching starts afresh.
- **A place now finds more.** A dataset with one file in Beirut lists all its
  files, including those elsewhere. Measured on the local catalog, a box
  around Beirut finds 43 assets this way, against 21 by each asset's own.

## Revisit when

Datasets get a footprint of their own in `kb`, semantic search joins the
switch, or a search must span several kinds at once.
