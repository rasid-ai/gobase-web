# Map

The map half of the workspace. Layout — where the chat panel sits, page
composition — is in context/ui-rules.md. MapLibre GL, per docs/adr/003.

Point inspection and drawing an asset's vector data are built. Area
questions and answer layers are not.

## Interaction modes

Three mutually exclusive modes: **navigate**, **point**, and **draw area**.

## Point inspection — built

Clicking a point in point mode lists every catalog asset whose coverage
includes it, grouped by data type. Data types come from the knowledge base
and are never enumerated in portal code (context/integrations/kb.md). A
point nothing covers shows nothing at all — no panel, no error.

Selecting an asset shows its metadata and draws its footprint. Metadata is
whatever the catalog holds for that asset: there is no fixed field set and
it differs by data type. Clearing the selection removes that asset's
metadata and its footprint; the list of assets stays open so another can be
picked. Drawn data layers are **not** cleared with the selection — see
below.

## Drawn vector data — built

Each asset in the list has its own control to draw it. That reads the
asset's features from the lake and renders them: polygons, lines and points
together, since one file may hold all three. The server caps how many
features it returns; when it does, the row says how many are shown.

Drawn layers outlive the selection that loaded them (docs/adr/008). Picking
another asset, clearing a selection or clicking a new point all leave them
on the map, because the point of drawing them is to see several at once. A
panel lists what is drawn, and is the only way to hide, remove, or clear
them. Hiding a layer never refetches it.

Only vector assets can be drawn today. The endpoint that serves them names
that modality rather than inferring it (docs/adr/008); other modalities get
their own endpoints. This is the one exception to the rule above that data
types are never enumerated in portal code — it applies everywhere else,
and in particular nothing groups, labels or displays a fixed list of
types.

## Area questions — not built

The user draws a rectangle and asks a question scoped to it. The geometry
travels with the question, and retrieval is restricted to that area. When
the area is cleared the rectangle disappears from the map.

## Answer layers — not built

An answer carrying a vector layer renders it on the map, and the user can
hide and re-show it without re-asking. An answer referencing a raster
asset displays it as tiles over the basemap when the answer completes.
