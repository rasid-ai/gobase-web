# Atlas — the map workspace

The map half of the Atlas page, at `/map`. Layout — where the chat panel
sits, page composition — is in context/ui-rules.md. MapLibre GL, per
docs/adr/003.

Point inspection, drawing an area, drawing an asset's vector data, and
searching the catalog by meaning are built. The map side of Ask — sending the
area with a question, and drawing an answer's layers — is built; the answers
themselves wait on the agent (specs/ask.md).

## Opening view — built

The map opens on Lebanon, the area the portal is operated for, zoomed to
fit the whole country. It is a starting point and not a boundary: panning
and zooming anywhere is unrestricted, and the view is not remembered
between visits.

## Interaction modes

Four mutually exclusive modes: **navigate**, **point**, **draw area** and
**semantic**.

Navigate leaves clicks to the map. Point inspects what a click lands on.
Draw area traces a polygon. Semantic takes a question instead of a click
(below). Switching mode changes what the next click does and nothing else —
it does not clear a point or an area already chosen, and a semantic
question and its matches survive a switch away and back.

## Point inspection — built

Clicking a point in point mode opens the panel on the right, which browses
the catalog assets whose coverage includes it, in three levels
(docs/adr/016):

1. **Datasets.** Every dataset with an asset here, by its readable label,
   with how many assets and of which data types. A search box above filters
   them by name.
2. **Files.** Opening a dataset lists its assets here, by name, each with
   its data type, format, and a control to draw it. A search box searches
   their metadata — the same catalog text, and the same exact match, as on
   the Assets page (specs/assets.md) — and a data type choice (All, or one
   type) sits beneath it. The choice appears only here: among datasets a
   type means nothing. Its options and counts are what the catalog reported
   for this dataset here, never a list held in the portal, and it is shown
   even when there is one type, because then it says what the dataset holds.
   **Datasets** goes back, to the dataset search as it was left.
3. **Detail**, below.

Opening a dataset starts its search empty. Up to 200 files are listed; past
that the panel says how many there are and to search to narrow.

A point nothing covers shows nothing at all — no panel, no error. A dataset
search that matches nothing says so, and the panel stays. A new point or a
new area starts the panel again at its datasets with nothing typed.

Data types come from the knowledge base and are never enumerated in portal
code (context/integrations/kb.md).

## The detail — built

Selecting an asset shows its name and metadata and draws its footprint, with
its own control to draw its data — the same control the list row carries, so
the two panels offer the same actions. The panel opens either because a click
found assets here, or because an asset arrived in the URL; nothing else opens
it. Metadata is whatever the catalog holds for that asset: there is no fixed
field set and it differs by data type. Clearing the selection removes that
asset's metadata and its footprint and returns to the files it was chosen
from, with their search and data type as they were. Drawn data layers are
**not** cleared with the selection — see below.

**Plain values first, tables when expanded.** Collapsed, the detail shows
the plain values and says how many more there are. Expanded, the panel
widens and shows every structured value as a table: a vector file's
`columns` as one row per column, a raster's `bands` and `stats` the same
way, and its `tags` as key and value rows, nested as deep as they go. What
counts as structured is decided by the value's shape — an object, or a list
holding objects — never by its key. A list of plain values, such as
overview factors, reads fine on one line and stays one. No value is ever
shown as raw JSON, and text that happens to hold JSON stays text.

**The footprint gives way to the data.** It is a stand-in for content you
cannot see, so once that asset's own features are drawn the outline goes: it
would otherwise box in the very thing it was describing. Hiding the layer
brings it back, because then there is nothing to see again.

## Go to a place or a coordinate — built

One box on the map takes either: a coordinate pair, or the name of a place.
Whichever it is, going there moves the map, lands the marker, and runs the
same assets-at-point lookup. The result is the same as having clicked that
spot by hand, including clearing whatever asset was selected, and it switches
the mode to point so the mode control keeps describing what a click will do.

**What is typed decides which it is.** Two numbers are a coordinate; anything
else is a place to search for. Nothing has to be chosen in advance, and a
coordinate never reaches the geocoder.

### As a coordinate

Input is **latitude first** — the order every mapping site writes and the
order a pasted pair arrives in. The API takes longitude first, so the swap
happens in the interface and nowhere below it. One box rather than two, so a
pasted pair needs no editing; a comma or a space separates the values.

A coordinate that falls outside the valid range is a form error shown next to
the box, and nothing moves. A coordinate that is valid but has no data under
it still moves the map and places the marker — the panel simply does not
open, exactly as for a click on empty space.

### As a place

Once typing pauses, up to five candidate places are offered under the box,
each with its name and its coordinate. Nothing happens until one is picked:
the box never guesses, not even when there is only one candidate, because
going somewhere nobody chose is worse than waiting.

Picking one goes there. A place that came back with an extent is framed by
it, rather than zoomed to a fixed distance — a country and a street corner
are not the same trip — and framing stops short of the closest zoom the
basemap can draw, as it does for an asset's coverage.

Searching starts at three characters, and a search is one request per pause
in typing rather than one per letter. Both limits exist because every search
is billed (docs/adr/011).

Text that matches no place says so. If the geocoder cannot be reached, or the
portal has no key for it, the box says address search is unavailable and does
not ask again — a coordinate still works the whole time.

### Its address

Picking a place puts it in the URL as `?place=<name>&bbox=<area>`, so the
view can be reloaded and sent to someone (docs/adr/011). What comes back is
the framing and the name — not the marker or the panel, which are the result
of an action rather than of the area. The same link filters the Assets page
to that area.

An area in the URL that cannot be read is removed, reported once, and the map
opens where it always does.

## Arriving from the Assets page — built

`/map?asset=<id>` opens the map on that asset: the view frames its coverage,
its footprint is drawn, and its metadata panel is open — the same end state
as clicking it in the list after clicking the map, but without either click.
There is no point marker, because no point was chosen.

Framing stops short of the closest zoom the basemap can draw. An asset's
coverage may be a single point, which has no area to frame; zooming all the
way in on one would land past the last tile there is and show an empty
screen instead of a place.

The parameter is the selection rather than a copy of it, so the link survives
a reload and can be shared (docs/adr/009). Clearing the selection removes the
parameter; without that the map would re-select the asset immediately and the
panel could not be closed.

Only the coverage is drawn. Drawing the asset's features stays the separate
action below — offered on the metadata panel itself, because an asset
reached this way never passes through the list of assets at a point and
would otherwise have to be found again by clicking the map.

## Drawing an area — built

In draw-area mode the user clicks out a polygon, one corner per click, and
closes it by clicking the first corner again or pressing Enter; Escape
abandons it. The finished polygon is outlined on the map and becomes the
area: the panel browses every catalog asset whose coverage overlaps it —
datasets, then files — exactly as for a point. An area nothing overlaps
shows nothing at all.

A point and an area are one selection, not two. Clicking a point, or going
to a searched place, clears the area; finishing an area clears the point.
Drawing again replaces the area. Clear area removes it, and changing mode
leaves it where it is, so you can switch to navigate and pan around what you
drew.

An area has at most 100 corners and its edges cannot cross. The draw tool
refuses the click that would break either rule, and says why; the server
checks both again, because neither PostGIS nor DuckDB refuses a polygon that
crosses itself — each silently returns a wrong answer (docs/adr/014).

The area is not in the URL. It never leaves the map, so by the rule in
docs/adr/011 it has no parameter, and `?bbox=` keeps meaning the searched
place. A drawn area is not a link that can be sent to someone.

## Drawn vector data — built

Each asset has its own control to draw it — in the list, and on the metadata
panel once one is selected. That reads the asset's features from the lake and
renders them: polygons, lines and points
together, since one file may hold all three.

A layer shows the area the map is showing, and follows it: pan or zoom, and
what is drawn is read again for where you are now (docs/adr/012). There is
no cap on an asset any more. What there is instead is a budget per area —
a view of a whole city can hold more features than are worth reading, and
when it does the panel says how many are shown and that zooming in gets the
rest. Zoom in and the layer comes back whole, because a smaller area is
read in full.

While an area is drawn, it replaces the view: a layer shows the features
inside the polygon, and panning or zooming changes nothing about what is
drawn (docs/adr/014). A feature crossing the outline is drawn whole — the
map shows what the file holds and never cuts a geometry at the edge. The
same budget applies, and when it is reached the panel says to draw a
smaller area, because zooming in does nothing to an area.

Drawn layers outlive the selection that loaded them (docs/adr/008). Picking
another asset, clearing a selection or clicking a new point all leave them
on the map, because the point of drawing them is to see several at once. A
panel lists what is drawn, and is the only way to hide, remove, or clear
them. Hiding a layer never refetches it, and a hidden layer does not follow
the map.

A layer that cannot be read says so in the layers panel, and stays. It is
read again on the next move, so a failure is a state of the layer rather
than a passing notice.

Only vector assets can be drawn today. The endpoint that serves them names
that modality rather than inferring it (docs/adr/008); other modalities get
their own endpoints. That is the one exception to the rule above that data
types are never enumerated in portal code — it applies everywhere else,
and in particular nothing groups, labels or displays a fixed list of
types.

The control itself is offered for every asset, whatever its type. Which
types have features to draw is the knowledge base's to say, not the
interface's, so an asset with none says so when asked rather than being
quietly refused a button.

## A count and a filter — built in the API, not on the page

`GET /api/map/assets/{id}/summary` counts a vector asset's features and
returns a few of them (docs/adr/028). It exists for the Ask agent's answers;
no page calls it yet.

- **The place** is a `bbox`, a drawn `area`, or neither for the whole file.
  The count is exact for both: a bbox here tests each feature's real shape,
  where `/data` tests bounding boxes.
- **`sample`** (0–10, default 5) is how many rows come back: the first
  matching features in file order, properties only.
- **The filter** is three parameters, sent together: `filter_column`,
  `filter_op` and `filter_value`.
  - `equals` and `in` match text whatever its case, and other types by
    value. `in` takes up to 20 values, by repeating `filter_value`.
  - `contains` is for text columns, whatever the case. `%` and `_` mean
    themselves.
  - `<` and `>` are for numbers, dates and timestamps.
  - A null never matches.
- **A filter the asset cannot take is a 400** that names the parameter: an
  unknown column (the message lists the real ones), an operator the
  column's type does not allow, a value that is not of its type, or a nested
  column.

`/data` takes the same filter, so a layer can show exactly the features a
count was of. The map does not send one yet. An unfiltered page keeps the
ETag it had.

## Raster figures and a clip — built in the API, not on the page

Two endpoints read a raster's pixels over a place (docs/adr/029). They exist
for the Ask agent's answers; no page calls them yet.

`GET /api/map/assets/{id}/raster-stats` says what the pixels inside a place
hold.

- **The place** is a `bbox`, a drawn `area`, or neither for the whole
  raster. A pixel counts when its centre is inside the place; a place
  smaller than a pixel counts the pixels it touches, and a place with no
  size (a point) counts the one pixel it is in.
- **`pixels`** is how many pixels are inside the place.
- **A place wider than the raster** is cut to it. A zoomed-out map view
  over a raster measures the whole raster. A raster that crosses the
  antimeridian (180°) is measured on both sides of it.
- **`bands`** gives each band's `min`, `max` and `mean` over the pixels that
  hold data, and `valid_percent`, their share of `pixels`. An alpha band
  is not listed. A small figure is not rounded to zero.
- **`classes`** is for a classified raster (one whole-number band with a
  legend in its `classes` tag): each value's `name`, `pixels` and `share` of
  the pixels that hold data, largest first, at most 256. It is null for any
  other raster.
- **`other_classes`** sums every value beyond those 256 (`values`, `pixels`,
  `share`). It is null when `classes` holds them all.
- **`approximate`** is true when the place holds more pixels than the server
  counts (`RASTER_STATS_MAX_PIXELS`, 4,000,000). The raster is then
  read at reduced size, `pixels` counts that smaller grid, and the figures
  are close, not exact.
- **A place that misses the raster** is a 200 with `pixels: 0` and no
  figures.

`GET /api/map/assets/{id}/clip.tif` downloads the pixels over a place as a
GeoTIFF.

- **It needs a place:** a `bbox` or an `area`.
- **The clip is a rectangle.** A drawn area is clipped to its envelope, not
  masked to its shape.
- **It is the raster's own grid and CRS**, not resampled, with its nodata
  or mask, colours, band names and legend. Only tags on a fixed list are
  carried, and none that names a path: a short tag with any slash in it
  is left out, and a sentence that has the shape of a path.
- **It is capped by size** at `RASTER_CLIP_MAX_BYTES` (64 MB of pixels
  before compression: width x height x bands x bytes per value). A larger
  place is a 400 that gives its pixel count, its size and the size
  allowed. A place that misses the raster is a 400.
- **The download is named** `<asset name>_clip.tif`.
- **The browser keeps it** and asks before reusing it (an ETag and
  `private, no-cache`, as for a document's PDF). A copy that is still good
  is a 304 with no read of the lake.
- **A HEAD request** answers with the status and headers a GET would, and
  builds no clip. Its `Content-Length` is 0, not the file's.
- **`If-None-Match`** matches whether the ETag comes back as `W/"x"` or
  `"x"`.
- **A clip the portal could not write** to its own disk is a 503 that says
  so, not a 502.

Both answer 404 for anything but an active raster, 503 when the lake cannot
be reached, and 502 when the raster cannot be read. A lake that answers
with an error of its own (5xx, throttling, an expired token) is a 503 too.
A JWT or an API key may read both.

How long a failing lake holds a request, measured on 2026-11-10:

| The lake | Answer | After |
|---|---|---|
| refuses the port, or does not resolve | 503 | under 1 second |
| drops every packet | 503 | 15 seconds |
| connects, then says nothing | 503 | 24 seconds |
| sends headers and then stalls, or drips | 503 | 8 seconds |
| is slow but alive | 503 | `RASTER_READ_TIMEOUT_SECONDS` (60), plus the chunk of rows or strip it is on: a few megabytes |

A statistics read goes a chunk of rows at a time, all bands at once, and
looks at the time limit between chunks. Through a link throttled to
400 KB/s, a long, thin place that ran 114 seconds now answers in 52; at
150 KB/s, 303 seconds became a 503 after 60 to 69.

The Ask agent, the one caller of `raster-stats`, stops waiting after 15
seconds. A read that takes longer goes on here until it ends or reaches a
bound above, and its worker stays held.

Not handled: a raster whose extent has no lon/lat box (the whole world in
Mollweide), or one stored with longitudes from 0 to 360. With a place each
is a 422 that says so; without one, `raster-stats` still measures the whole
raster. The catalog holds neither. A world-wide grid that reaches less than
a pixel past 180° is handled.

Not built: any page using them. The Ask panel shows a `raster` reference as
an asset chip and offers no download yet (specs/ask.md).

## Semantic search — built

In semantic mode the panel on the right is a question box and, under it,
the assets closest in meaning to the question (docs/adr/018). Type a
subject, a place, a kind of document — "airport security", "economic
impact of reopening an airport" — and send it; one request per question,
never one per keystroke. The ten best matches are listed, best first.

The question is embedded by the data platform's document service with the
same model that embedded the catalog's cards, and the cards are ranked by
cosine similarity (context/integrations/godoc.md, kb.md). Cards only — the
shallow search; passages inside a document are not searched. Meaning only —
the clicked point and the drawn area do not narrow it. The search names no
data type: whatever the data platform has given a card to comes back, which
is documents today.

Each match is the same row as the point and area lists — its name opens
the detail, Draw puts its features on the map — and, since a match is not
inside a dataset the way a point's files are, the row says which dataset it
is in. A document whose PDF the catalog records adds **Open** beside Draw:
the PDF opens in a new tab, as from the Assets page (specs/assets.md). Two
actions and no more. A document has no vector data, so Draw on one says
"No vector data to draw", as it does anywhere.

Nothing typed yet shows a line saying what the panel is for. While the
answer is read, placeholder rows. A question nothing is close to says so.
A service that is down or not configured says semantic search is
unavailable; any other failure offers Try again. How well a match scored is
not shown — the order carries it.

Not built here: narrowing the matches to a place, showing where a match's
dataset is (the answer carries the dataset's envelope as `dataset_bbox`
for it), searching inside a document for a passage, and opening a PDF at
the page a passage is on.

## Area questions — the map side built

A question asked in the Ask panel carries the map's state as data: the
viewport, and the drawn area or the clicked point, and the selected asset
(specs/ask.md). The line above the question box says which ("Asking about ·
this area"). Restricting retrieval to the area is the agent's, through the
catalog endpoints its tools call (docs/adr/024), and is not built.

The agent counts through the summary endpoint above, which is exact for a
window as for an area. `/data` still matches a window by bounding box
(docs/adr/012), so a layer drawn for a window can show a few features the
count left out.

## Answer layers — built, without the filter

An answer carrying a vector layer renders it on the map, and the user can
hide and re-show it without re-asking: its chip in the answer toggles it, and
it is in the layers panel like any other (specs/ask.md). It is drawn through
the same layer store as Draw, so it follows the drawn area or the view. The
answer's own area and filter are not applied yet: `/data` takes the filter
since 2026-11-10 (docs/adr/028), but the layer store does not send it.
Not built: an answer referencing a raster asset displaying it as tiles
over the basemap when the answer completes.
