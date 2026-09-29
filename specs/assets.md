# Assets — browsing the catalog

The third page in the shell, at `/assets`. It answers "what do we hold?",
which is the question the map cannot answer: the map tells you what covers
a point you already chose.

Built, except where said otherwise below.

## Two ways to browse

A switch at the top of the filter rail chooses between them (docs/adr/016):

- **Datasets** — the page opens here. First the datasets, then the assets of
  the one you open.
- **Assets** — every asset at once, as one list.

The page is called Assets in both; the count beside the title says what is
listed. Switching clears the search and the open dataset, and keeps the date
and the area, which describe when and where rather than what.

## Datasets

A dataset is the top folder a file came from in the raw bucket
(`assets.dataset`, context/integrations/kb.md). Each shows as a card with its
readable label — `points_of_interest_hotsom` reads "Points of interest
hotsom" — its name as the catalog holds it, how many assets it has, and how
many of each data type.

The label is spaced and in sentence case, and nothing else: the knowledge
base is read-only, so the data's own spelling stays ("Goverment").

The search box searches dataset **names** here — the label or the raw name —
and nothing inside them. No data type filter is offered, because a dataset
holds several types and choosing one among datasets means nothing. The date
and the area narrow the list to datasets with assets in that window or place,
and each count is the number you will find on opening the dataset.

Datasets are listed by label and are not paged. An asset with no dataset is
in none of them; it still appears in the Assets mode.

Opening a dataset shows its assets, exactly as the list below, with the
dataset's label as the title and **All datasets** to go back. Inside, the
search box starts empty and searches the assets' metadata, and the data type
filter appears. Going back finds the dataset search as it was left.

The mode and the open dataset are not in the URL, because they cross no page
(docs/adr/011). The browser's Back button leaves the page rather than
stepping out of a dataset.

## The list

Every active asset in the catalog — or in the open dataset — newest ingestion
first. Superseded and failed assets never appear. Each one shows its data
type, its file format, its dataset's label (except inside that dataset, where
every card would say the same), its name, its id, where it sits in the
catalog's topic tree, its size, and the day it was ingested.

**An asset has no name of its own.** The catalog holds no name column, so
the page shows one derived from the asset's source path with the extension
removed — `gis_osm_boundaries_07_1` (docs/adr/010). This is the name that
sorting by name uses.

Data types are whatever the knowledge base says they are. Nothing on this
page holds a list of them, groups by a known set, or gives one a colour the
others do not get; every type is shown the same way, in the type's own
words.

The page shows 12 assets at a time and says which of them these are — `13–24
of 212`. Numbered pages sit under the grid, with a step either side; they
appear only once there is more than one page. Changing a filter or the sort
returns to the first page, because page 4 of one list has nothing to do with
page 4 of another.

The server pages by offset, not by cursor (docs/adr/010): the list sorts five
ways and reports a total, and a cursor over one id serves neither.

## Filtering

Four filters, and they combine:

- **Search** — the asset's catalog text (docs/adr/016): its file name,
  dataset and dataset label, topic, format, data type, summary, layer names,
  the column names of a vector file and the tag values of a raster. So
  `shapeName` finds the boundary files by a column, and `water` finds the
  land-cover rasters by a class in their tags. Tag keys are not searched —
  every raster has a `year`.

  It is an exact match: what is typed must appear, as typed, inside one
  field, in any case. It is not split into words and forgives no typos. It is
  matched literally, so the underscores that fill these names are not
  wildcards.
- **Data type** — any number of types at once. None selected means all.
  Offered in the Assets mode and inside a dataset, not among datasets.
  The list of types, and the count beside each, comes from the server.
  Those counts answer "what else is there", so they do not shrink to the
  type already selected.
- **Date of ingestion** — any time, or the last 7, 30 or 90 days.
- **Area** — assets whose coverage overlaps a place. Set by searching for
  one in the same box as the name filter, and shown underneath as a chip
  that removes it.

A filter that matches nothing says so, and offers to clear the filters,
rather than claiming the catalog is empty. An empty catalog says that
instead. Clearing is only offered when there is something to clear.

## Searching for a place

The search box does two jobs at once. What is typed filters the page straight
away — dataset names among datasets, asset metadata everywhere else — and the
same text is offered to a geocoder underneath the box, under a **Places**
label.

Both answers are available and you choose. That is how "Beirut" stops being
ambiguous: nobody has to decide in advance whether it names an asset or a
place, because the page answers both ways and lets you pick the one you meant.

Picking a place sets the area filter and **leaves the search alone** — the
two combine, so an area plus a search is a question you can ask.

Searching starts at three characters and runs once per pause in typing rather
than once per letter, because every search is billed (docs/adr/011). Text that
matches no place says so; a geocoder that cannot be reached says that instead,
and is not asked again.

## The area is an address

The area lives in the URL as `?place=<name>&bbox=<area>`, so a filtered list
survives a reload and can be sent to someone. It is the same parameter the map
uses, so an area found on one page carries to the other (docs/adr/011).

The filter matches assets whose **coverage overlaps** the area — not only
those wholly inside it. An area in the URL that cannot be read is removed,
reported once, and the whole catalog is shown.

## Sorting

Newest or oldest ingestion, name in either direction, or by data type.

Assets ingested in the same run share one timestamp — today that is the
entire catalog — so ordering by ingestion alone cannot separate them. The
server breaks the tie by asset id, which is what stops a second page from
repeating rows the first page already showed.

## Locating an asset on the map

Each asset links to its place on the map. Following it opens the Atlas page
framed on that asset's coverage, with its footprint drawn and its metadata
open — the same panel a click on the map would have opened, without the
click.

The link is an address: `/map?asset=<id>` (docs/adr/009). It survives a
reload and can be sent to someone else. Clearing the selection on the map
removes it, so the page does not snap back to the asset.

Following the link draws the asset's **coverage**, not its data. Drawing
the features themselves stays the separate, explicit action it is on the
map (docs/adr/008) — and the metadata panel that opens carries that
action, so an asset arrived at this way can be drawn without hunting for
it again. Drawing it replaces the coverage outline with the features
themselves.

An asset the catalog holds no coverage for offers no link. There would be
nowhere to go.

## Not built

- **Drawing the area on the map.** An area can only be reached by naming
  a place. Drawing a rectangle and filtering to it arrives with the area
  question path (specs/map.md).
- **Opening an asset in place.** Selecting an asset shows it on the map;
  there is no detail view on this page.
- **Word-by-word or forgiving search**, and showing **why** an asset matched
  (which field held the text).
