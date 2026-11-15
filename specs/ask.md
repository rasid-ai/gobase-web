# Ask — Q&A over the knowledge base

The chat renders inside the Atlas page (`/map`) as a docked panel on the
right; layout is in context/ui-rules.md. The engine is `gobase-agent`, a
separate service this backend calls (docs/adr/023); the backend's `apps/chat`
is a gateway to it and runs no model. The contract is in
context/integrations/agent.md.

**Built (2026-11-09):** the gateway and the panel, tested against a faked
agent and checked live against a stub. **Built (2026-11-10):** the three
backend endpoints the agent's tools were missing (docs/adr/024; "What the
backend serves the agent's tools" below), each run end to end with the real
agent on a developer's machine. All nine of the agent's tools are built
(`doc_search` and `doc_passages` on 2026-11-15). **Not built:** a deployed
agent. So Ask answers nothing yet in any deployed portal; with no
`AGENT_URL` the panel says Ask is unavailable.

## Answering

A question goes to `POST /api/chat/sessions/{id}/turns` with the map's
context, and the answer streams back as server-sent events: `text` pieces,
`reference`s as the agent finds them, then `done` with the checked whole, or
`error` when it stopped part-way. The panel shows the text as it arrives,
with a caret, and the header says "Answering". `step` events (the agent
looking something up) are not shown: no tool trace in the UI.

Every factual claim about the data is meant to cite a catalog asset. The
agent enforces that (only ids its tools returned this turn); the panel shows
the citations the answer carries. An answer with no citations shows none —
the honest empty answer.

If an answer stops part-way — the agent's `error` event, a stream that ends
with no last event, a connection that breaks or goes silent — what streamed
stays on screen with "The answer was cut off." and a Try again button, and it
is never shown as whole. Stop ends the answer the same way, as "The answer
was stopped." Try again asks the same question again in the same session, in
the stopped turn's place.

A question the backend refuses before anything streams (502, 503, no answer
at all) goes back into the box with a toast: "Couldn't send the question.
The Ask service returned 502."

## What an answer shows

The agent sends one list of references: everything its tools returned, each
with a short handle (`A1`), its name and data type. The answer cites inline
with markers, `[A1]`. The panel shows only what the answer cited
(`features/ask/references.ts`):

- **Marks**, in the text: each marker becomes a small numbered button, 1, 2,
  3 in order of first citation in that answer. Selecting one opens the asset,
  as its chip does.
  A bracket the turn has no reference for (`[sic]`) stays as text.
- **Citations**, under the text: every cited asset, in marker order and with
  the same number — name, data type, and `p. N` for a passage. An asset cited
  at a page gets no second chip without one. Selecting one opens a
  document's PDF in a new tab, at the cited page. Anything else, or a PDF
  that can't be fetched, opens the asset's metadata in the map's pane. The
  name and type come with the reference; a reference without them is looked
  up in the catalog. (Until 2026-11-15 a box below repeated every cited
  asset and raster as an "Assets" list; it showed the same chips twice and
  is gone.)
- **On the map**, in a box below: the `layer` references, each with the
  count the answer gave. A layer that arrives while the answer streams is
  drawn at once; its chip hides and shows it.

A `frame` reference moves the map when it arrives, and "Framed to the
answer" under the text moves it back there. A frame may carry the handle of
the place the agent found (`L1`). A place is never cited, so it gets no mark
and no chip.

A reference counts as cited when its handle appears as a marker in the text,
so chips appear while the answer streams, as it cites them, and after an
answer that stopped early. At `done`, and in a stored turn, the agent's own
`cited` flag is also honoured: `cited: false` hides a chip, `cited: true`
shows one. A reference with no handle and no flag is shown, as before handles.

Not built: a raster's clip download and its figures in the panel (the
endpoint exists since 2026-11-10, `GET /api/map/assets/{id}/clip.tif`, and a
`raster` reference carries the `area` to send it and the `stats` to show;
the panel shows the reference as an asset chip only), a passage opening at
its page image (a passage opens the asset's metadata, from which the PDF
opens), and the hover that shows a citation's dataset label.

## Area scope

What the question is about travels with it as data: the viewport always, the
drawn area or the clicked point when there is one, and the selected asset.
The line above the box says which: "Asking about · this area · 1 asset
selected", "this point", or "the current view".

Restricting retrieval to that area is the agent's job, through the backend
endpoints its tools call.

**An answer's layer is drawn for its own place and filter** (2026-11-15).
The layer keeps the reference's `area` (or `bbox`) and `filter`, and `/data`
reads exactly those (docs/adr/028), so the map shows what the chip's count
counted, not the whole asset in the current view. Moving the map or drawing
an area doesn't change it. The chip reads "<asset> · answer's area", or
"whole asset" when the answer had no place, then the filter if there is one
("poi · answer's area · amenity in hospital, clinic").

**Several layers of one asset** (2026-11-15). An answer may count several
things in one asset ("2 schools and 7 hospitals" from one points-of-interest
file). Each place and filter is its own layer, with its own chip and count,
and they sit side by side on the map. Each is also separate from the asset's
own catalog layer. A layer's id is the asset's id for a catalog layer, and
the asset's id plus a short hash of the place and filter for an answer's
(`frontend/src/features/workspace/layerId.ts`).

## Sessions

Sessions are private to their owner: the agent keeps each user's under that
user's prefix in its bucket, and the backend always names the caller
(docs/adr/025). `portal` stores nothing about chat.

The history button lists the user's sessions, newest first, with their day
("today", "Oct 31") and a delete button. Opening one reads it back with every
turn in order, its references included, so its citations and layers return;
its layers come back hidden, and a click draws them. A new chat gets a fresh
UUID from the SPA, and the agent starts a session for it on the first
question.

The conversation lives with the page, not the panel: closing the panel keeps
an answer streaming, and an answer that ends while it is closed puts a dot on
the Ask toggle.

## States

Closed (the toggle, with its dot), empty session (a hint and three example
questions), streaming, incomplete, unavailable (the session list answered
503: the box is disabled and says so), loading a session (skeletons, and no
question box), and an error on send (the toast). Each is in
`context/designs/GeoPortal.zip`, and each was checked in a browser, light and
dark, against a stub agent on 2026-11-09.

## What the backend serves the agent's tools

The agent's tools read the knowledge base through this backend
(docs/adr/024). Four of them use endpoints the pages already use. Three
endpoints exist for the agent's answers alone:

- **A passage by its id (built 2026-11-10).** `GET
  /api/catalog/assets/{asset_id}/passages/{chunk_id}` returns one passage of
  a document: `asset_id`, `chunk_id`, `text`, `heading_path`, `page_start`,
  `page_end`, `pages_with_boxes` and `chunk_type`. Pages count from 1, as in
  deep search. It answers 404 when the id is not an active document, when the
  document has no passages indexed, or when the chunk is not in that
  document; 400 for a chunk id that is not one; 503 when the chunk index
  cannot be reached and 502 when it fails. A document whose PDF was never
  recorded can still be read.

- **A features summary (built 2026-11-10).** `GET
  /api/map/assets/{asset_id}/summary` returns `asset_id`, `total` and
  `sample` for a vector asset: the exact number of features in a `bbox` or a
  drawn `area` (or the whole file), and the properties of the first few, with
  no geometry. It takes a simple attribute filter, which `/data` takes too
  (specs/map.md, "A count and a filter"; docs/adr/028).

- **Raster figures and a clip (built 2026-11-10).** `GET
  /api/map/assets/{asset_id}/raster-stats` returns `asset_id`, `pixels`,
  `approximate`, `bands`, `classes` and `other_classes` for a raster: per-band statistics
  over a `bbox` or a drawn `area` (or the whole raster), and each class's
  share for a classified raster. `GET /api/map/assets/{asset_id}/clip.tif`
  downloads the pixels over the place as a GeoTIFF. The agent's `raster_clip`
  tool calls the first; the second is for the client (specs/map.md, "Raster
  figures and a clip"; docs/adr/029).
