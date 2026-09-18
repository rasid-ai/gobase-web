# Assets — browsing the catalog

The third page in the shell, at `/assets`. It answers "what do we hold?",
which is the question the map cannot answer: the map tells you what covers
a point you already chose.

Built, except where said otherwise below.

## The list

Every active asset in the catalog, newest ingestion first. Superseded and
failed assets never appear. Each one shows its data type, its file format,
its name, its id, where it sits in the catalog's topic tree, its size, and
the day it was ingested.

**An asset has no name of its own.** The catalog holds no name column, so
the page shows one derived from the asset's source path with the extension
removed — `gis_osm_boundaries_07_1` (docs/adr/010). This is the name that
search matches and that sorting by name uses.

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

- **Name** — a substring of the derived name. What is typed is matched
  literally, so the underscores that fill these names are not wildcards.
- **Data type** — any number of types at once. None selected means all.
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

The search box does two jobs at once. What is typed filters the grid by asset
name straight away, exactly as it always has, and the same text is offered to
a geocoder underneath the box, under a **Places** label.

Both answers are available and you choose. That is how "Beirut" stops being
ambiguous: nobody has to decide in advance whether it names an asset or a
place, because the page answers both ways and lets you pick the one you meant.

Picking a place sets the area filter and **leaves the name filter alone** —
the two combine, so an area plus a name is a question you can ask.

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
