# Map

The map half of the workspace. Layout — where the chat panel sits, page
composition — is in context/ui-rules.md. MapLibre GL, per docs/adr/003.

Point inspection is built. Area questions and answer layers are not.

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
metadata, its footprint, and any vector or raster layer drawn for it; the
list of assets stays open so another can be picked.

## Area questions — not built

The user draws a rectangle and asks a question scoped to it. The geometry
travels with the question, and retrieval is restricted to that area. When
the area is cleared the rectangle disappears from the map.

## Answer layers — not built

An answer carrying a vector layer renders it on the map, and the user can
hide and re-show it without re-asking. An answer referencing a raster
asset displays it as tiles over the basemap when the answer completes.
