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
listed. Switching clears every filter (the search, the data types, the date
and the area) and the open dataset, so nothing stays applied that the rail no
longer shows (docs/adr/019). The sort stays: it orders and does not filter.

## Datasets

A dataset is the top folder a file came from in the raw bucket
(`assets.dataset`, context/integrations/kb.md). Each shows as a card with its
readable label — `points_of_interest_hotsom` reads "Points of interest
hotsom" — its name as the catalog holds it, how many assets it has, and how
many of each data type.

The label is spaced and in sentence case, and nothing else: the knowledge
base is read-only, so the data's own spelling stays ("Goverment").

The metadata search searches dataset **names** here — the label or the raw
name — and nothing inside them. No data type filter is offered, because a
dataset holds several types and choosing one among datasets means nothing.
The date narrows the list to datasets with assets ingested in that window, and
the area to datasets whose coverage overlaps the place (see Filtering). Each
count is the number you will find on opening the dataset.

Datasets are listed by label and are not paged. An asset with no dataset is
in none of them; it still appears in the Assets mode.

Opening a dataset shows its assets, exactly as the list below, with the
dataset's label as the title and **All datasets** to go back. Inside, the
metadata search starts empty and searches the assets' metadata, and the data
type filter appears. Going back finds the dataset search as it was left.

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

**A document is the exception.** Its source path is the parsed bundle the
data platform wrote, and nobody recognises `plan.bundle`; the page names it
after the PDF it was parsed from, extension kept — `Beirut airport - Case
Study - TiSO.pdf` (docs/adr/017). The title the parser read is shown under
the name when there is one and it is not the name again. The catalog holds
no size for a document, so the card shows its page count instead. Its
format is its file's — `pdf` — not the parser that read it; the parser is
in the detail on the map, as `parser`. Searching finds a document by its
PDF's name and its title as well as the rest.

## Opening a document's PDF

A document card offers **Open PDF**. It opens the PDF in a new browser tab,
in the browser's own viewer, fetched through the portal's API from the
bronze bucket (docs/adr/017) — the browser never touches the bucket. While
the file is fetched the button waits; if the file cannot be fetched the card
says so in place, and the button is there to try again.

The button is offered only when the catalog records the PDF. A document
without one — a bundle loaded without its source stamp — shows no button,
rather than one that fails.

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

- **Metadata search** — the asset's catalog text (docs/adr/016): its file name,
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
- **Area** — the assets of every dataset whose coverage overlaps a place
  (docs/adr/019). A dataset covers what its assets cover together, so a
  dataset in the place brings all of its files, including the documents and
  unparsed files that cover nowhere themselves. An asset with no dataset is
  matched by its own coverage. A dataset where no file has coverage (today
  `airports`) is in no place. Set by finding a place in the search box, and
  shown underneath as a chip that removes it.

A filter that matches nothing says so, and offers to clear the filters,
rather than claiming the catalog is empty. An empty catalog says that
instead. Clearing is only offered when there is something to clear.

## The search box

Three small icons under the box choose what it searches: **Metadata** (a
text-search icon), **Places** (a map pin) or **Semantic** (sparkles). It
searches one at a time, so a word is never a name and a place at once
(docs/adr/019, docs/adr/020). Each icon's name is its tooltip, and choosing
one puts the cursor in the box. The icons are quieter than the Datasets /
Assets switch on purpose: that switch changes what the page lists, and these
change only what the box is for.

- **Metadata** filters the page as you type: dataset names among datasets,
  asset metadata everywhere else. Nothing typed here goes to the geocoder.
- **Places** sends what is typed to the geocoder and filters nothing. Picking
  a place sets the area and empties the box.
- **Semantic** asks a question of the documents, by meaning. The box grows
  to three lines for it, with the Search button inside. It is sent when you
  press Enter or the Search button, never as you type, because each question
  is an embedding round trip; Shift+Enter breaks a line. The answer replaces
  the grid (see Deep search results).

Each filter the box set is shown under it as a chip named by its kind:
**Place**, **Semantic**, and **Metadata** while the box is on another kind.
That way a place, a question and a search for the same word cannot be
mistaken for each other. A place combines with either of the other two. A
question and a metadata search never stand together: they share the box, so
choosing Semantic clears the metadata search and choosing Metadata clears the
question. Switching the box to Places changes neither.

A place search starts at three characters and runs once per pause in typing
rather than once per letter, because every search is billed (docs/adr/011).
Text that matches no place says so; a geocoder that cannot be reached says
that instead, and is not asked again.

## Deep search results

While a question is active the grid, in both modes, lists the **documents**
whose passages best answer it, best first, up to ten. Each is the document's
asset card with its matching passages (up to three) under the name. The
count beside the title says "N documents"; there is no sort, because the
answer is ranked. No similarity number is shown anywhere: the order carries
it (docs/adr/018).

A passage shows the section headings above it ("3 Security › 3.2
Checkpoints"), its page or pages, the kind of block it is (text, table,
chart…), and its text, clamped to three lines. Opening it shows the whole
text, then **the page itself**, rendered by the server with the passage's
area marked on it, and **Open PDF at p. N**, which opens the browser's
viewer at that page. A passage that runs over several pages offers a button
per page for the preview. The page is fetched only when a passage is opened.
A document whose PDF the catalog does not record offers neither.

The question is narrowed like every list: by the place (through the
datasets' coverage), by the date of ingestion, and by the open dataset — inside
one, the question is asked of its documents only. The data type filter is
not offered while a question is active, because only documents have passages.
Removing the question's chip brings the datasets or assets back as they were.

Only documents whose passages were embedded by the model the service runs
are searched; a document indexed by another model, or not indexed at all, is
never in the answer. "Semantic search is unavailable" means the embedding
service is not configured or cannot be reached. "No passages match that
question" means the search ran and found nothing close enough among the
documents in scope.

## The area is an address

The area lives in the URL as `?place=<name>&bbox=<area>`, so a filtered list
survives a reload and can be sent to someone. It is the same parameter the map
uses, so an area found on one page carries to the other (docs/adr/011).

The filter matches datasets whose **coverage overlaps** the area — not only
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
  there is no detail view on this page. A document's PDF opens in a new
  tab, not in the page.
- **Typing a coordinate** to set the area. The map's place search takes one;
  this box takes place names only.
- **Word-by-word or forgiving search**, and showing **why** an asset matched
  (which field held the text).
- **Opening a PDF at a passage's line.** The viewer opens at the page and
  the preview marks the passage; nothing records lines, only boxes on a
  0..1000 grid per passage.
- **Paging through passages, or a reranker.** A question lists the best ten
  documents and three passages each, ranked by cosine alone.
- **Highlighting the matching words in a passage's text.** The match is by
  meaning, and the index does not say which words carried it.
