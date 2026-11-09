# Ask — Q&A over the knowledge base

The chat renders inside the Atlas page (`/map`) as a docked panel on the
right; layout is in context/ui-rules.md. The engine is `gobase-agent`, a
separate service this backend calls (docs/adr/021); the backend's `apps/chat`
is a gateway to it and runs no model. The contract is in
context/integrations/agent.md.

**Built (2026-11-09):** the gateway and the panel, tested against a faked
agent and checked live against a stub. **Not built:** the agent itself, and
the backend endpoints its tools need (docs/adr/022). So Ask answers nothing
yet in any deployed portal; with no `AGENT_URL` the panel says Ask is
unavailable.

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

The agent sends one list of references. The panel shows it in three places
(`features/ask/references.ts`):

- **Citations**, under the text: every asset the answer drew on, once per
  asset and page — name, data type, and `p. N` for a passage. An asset cited
  at a page gets no second chip without one. Selecting one opens the asset's
  metadata in the map's pane.
- **Assets**, in a box below: the `asset` and `raster` references, to open.
- **On the map**, in the same box: the `layer` references, each with the
  count the answer gave. A layer that arrives while the answer streams is
  drawn at once; its chip hides and shows it.

A `frame` reference moves the map when it arrives, and "Framed to the
answer" under the text moves it back there.

Not built: a raster's clip download (its backend endpoint does not exist), a
passage opening at its page image (a passage opens the asset's metadata, from
which the PDF opens), and the hover that shows a citation's dataset label.

## Area scope

What the question is about travels with it as data: the viewport always, the
drawn area or the clicked point when there is one, and the selected asset.
The line above the box says which: "Asking about · this area · 1 asset
selected", "this point", or "the current view".

Restricting retrieval to that area is the agent's job, through the backend
endpoints its tools call. **Known gap:** a layer from an answer is drawn
through the same layer store as the asset pane's Draw, so it follows the
current drawn area or view, not the area and filter the answer counted.
`/data` has no attribute filter yet (docs/adr/022), so until it does, a
filtered layer draws more than the answer counted.

## Sessions

Sessions are private to their owner: the agent keeps each user's under that
user's prefix in its bucket, and the backend always names the caller
(docs/adr/023). `portal` stores nothing about chat.

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
