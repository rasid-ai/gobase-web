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

The page says how many assets match and how many are shown. It loads more
on request and keeps what it already has.

## Filtering

Three filters, and they combine:

- **Name** — a substring of the derived name. What is typed is matched
  literally, so the underscores that fill these names are not wildcards.
- **Data type** — any number of types at once. None selected means all.
  The list of types, and the count beside each, comes from the server.
  Those counts answer "what else is there", so they do not shrink to the
  type already selected.
- **Date of ingestion** — any time, or the last 7, 30 or 90 days.

A filter that matches nothing says so, and offers to clear the filters,
rather than claiming the catalog is empty. An empty catalog says that
instead. Clearing is only offered when there is something to clear.

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

- **Filtering by area.** Restricting the list to a box on the map is
  designed for but not built. It arrives with address search, which will
  turn a typed address into coordinates on both this page and the map.
- **Opening an asset in place.** Selecting an asset shows it on the map;
  there is no detail view on this page.
