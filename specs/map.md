# Atlas — the map workspace

The map half of the Atlas page, at `/map`. Layout — where the chat panel
sits, page composition — is in context/ui-rules.md. MapLibre GL, per
docs/adr/003.

Point inspection and drawing an asset's vector data are built. Area
questions and answer layers are not.

## Opening view — built

The map opens on Lebanon, the area the portal is operated for, zoomed to
fit the whole country. It is a starting point and not a boundary: panning
and zooming anywhere is unrestricted, and the view is not remembered
between visits.

## Interaction modes

Two mutually exclusive modes are built: **navigate** and **point**.

**Draw area** is specified below but is not built, and its control is not
shown. Showing a mode that switches and then does nothing is worse than
showing nothing; it returns when the area question path does.

## Point inspection — built

Clicking a point in point mode lists every catalog asset whose coverage
includes it, grouped by data type. Data types come from the knowledge base
and are never enumerated in portal code (context/integrations/kb.md). A
point nothing covers shows nothing at all — no panel, no error.

Selecting an asset shows its metadata and draws its footprint, with its own
control to draw its data — the same control the list row carries, so the two
panels offer the same actions. The panel opens either because a click found
assets here, or because an asset arrived in the URL; nothing else opens it.
Metadata is whatever the catalog holds for that asset: there is no fixed
field set and it differs by data type. Clearing the selection removes that
asset's metadata and its footprint; the list of assets stays open so another
can be picked. Drawn data layers are **not** cleared with the selection —
see below.

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

## Area questions — not built

The user draws a rectangle and asks a question scoped to it. The geometry
travels with the question, and retrieval is restricted to that area. When
the area is cleared the rectangle disappears from the map.

## Answer layers — not built

An answer carrying a vector layer renders it on the map, and the user can
hide and re-show it without re-asking. An answer referencing a raster
asset displays it as tiles over the basemap when the answer completes.
