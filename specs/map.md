# Spec: Map

Layout (where the chat panel sits, page composition) lives in
context/ui-rules.md. Retrieval behavior for area-scoped questions is
HLR-019; answer vector layers are produced per HLR-020.

---

**HLR-022** — WHEN a user clicks a point on the map, the system SHALL
list every catalog asset whose coverage includes that point, grouped by
data type.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a document and an imagery asset covering the point, and a third
asset elsewhere
WHEN the point is clicked
THEN the two covering assets appear under their data-type groups
AND the third does not appear

---

**HLR-023** — WHEN an asset in that list is selected, the system SHALL
show its metadata and draw its footprint on the map.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a clicked point's asset list
WHEN one asset is selected
THEN its catalog metadata is shown
AND its footprint renders on the map

---

**HLR-024** — The system SHALL let the user draw a rectangular area and
ask a question scoped to it.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a drawn rectangle
WHEN a question is submitted
THEN the question is sent with that geometry attached
AND the answer honors HLR-019

---

**HLR-025** — WHEN an answer includes a vector layer, the map SHALL
render it, and the user SHALL be able to hide and re-show it.
Priority: Must · Phase: MVP
**Done means:**
GIVEN an answer carrying a GeoJSON layer
WHEN the answer completes
THEN the layer renders on the map
AND toggling it hides and re-shows it without re-asking

---

**HLR-026** — WHEN an answer references a raster asset, the system SHALL
display it on the map as tiles.
Priority: Could · Phase: Phase 2
**Done means:**
GIVEN an answer citing a raster (COG) asset
WHEN the user requests its display
THEN the raster renders as tiles over the basemap
