# ADR-018: Semantic search over the catalog's cards, embedded by GoDoc

**Status:** Accepted · 2026-10-19

## Context

The map had three modes — Navigate, Point, Draw area — and its right pane
listed what the catalog holds at a point or in an area. The data platform
now parses PDFs and stores one embedding per document in `kb`: `doc_cards`
(`asset_id`, `embedder_id`, `vector`), today 4 cards from
`BAAI/bge-small-en-v1.5`, 384 dimensions, unit-normalised, with no ANN
index (context/integrations/kb.md). Nothing in the portal read them.

The user asked for a fourth mode: type a question or a sentence and see the
assets closest to it in meaning, listed like the point and area results,
each openable (the PDF, docs/adr/017) or locatable through its dataset. The
"shallow" search — cards in Postgres only, never the LanceDB chunk index —
and meaning only: no place narrows it yet. Documents today; videos, images
and CAD files later, once the data platform gives them cards.

Two facts fix the design. The question has to be embedded by the *same
model* that embedded the cards, and that model lives in the data platform's
document service, GoDoc's RAG server, which already exposes
`POST /rag/embed` for exactly this; the data platform's own search goes
through it (`gobase/modalities/document/client.py`). And the browser never
talks to a model service or to the knowledge base — the backend does
(docs/adr/011, CLAUDE.md).

## Decision

- **The mode is called Semantic**, fourth in the mode switch. A click does
  nothing in it; the question is typed at the top of the right pane and the
  matches are listed under it. The point, the area and the drawn layers are
  untouched by the switch, as by every other (specs/map.md); the question
  is kept, so switching away and back finds the matches where they were.
- **`GET /api/catalog/assets/similar?q=…&limit=10`** answers it. The
  backend sends the bare question to `{GODOC_URL}/rag/embed`, takes the
  model the server names and the vector, and runs the data platform's own
  card search (`gobase/modalities/document/store.py`): the browse CTE
  joined to `doc_cards`, `1 - (vector <=> question) AS score`, best first.
  The join is filtered on `embedder_id = <the model the server named>`: the
  data platform does not check this, and a second model's cards would rank
  nonsense against a vector they cannot be compared with.
- **No instruction prefix.** The cards were embedded as plain text; a query
  embedded differently from its corpus ranks worse, not better. The portal
  sends what was typed.
- **Nothing names a modality.** The join is on cards, not on `document`;
  whatever the data platform gives a card to comes back the same way.
- **A match is a list row plus `score` and `dataset_bbox`** — the envelope
  of every active asset in the match's dataset, null when none has
  coverage. A document has no coverage of its own, and "where is this
  about" is answered by the dataset it sits in. The score is in the
  contract and not on the screen: rank order carries it, and the rules keep
  similarity numbers out of answers (context/ui-rules.md).
- **The service is configured like the geocoder.** `GODOC_URL` and
  `GODOC_TIMEOUT_SECONDS`, defaults in settings, only
  `apps/catalog/godoc.py` names it; a blank URL answers 503 before any call
  and the pane says semantic search is unavailable, so the portal runs
  without the service. Unreachable is 503, a refused request 502, and the
  question never reaches a log: only exception types are logged, because the
  question is chat content (CLAUDE.md).
- **GET with `q`**, as `places_search`, so React Query caches and keys it.
  The question lands in the access log's request line, as a place search
  does; that is the trade accepted for both.
- **In the pane, each match is the same row** as the point and area lists
  (`AssetRow`: Details, Draw), naming its dataset, with **Open** beside Draw
  when the catalog records the document's PDF — two actions, no more, which
  is what the user asked for after trying a version with a third. Draw is
  offered for every row, as everywhere else; a row with nothing to draw says
  so when asked. `dataset_bbox` stays in the contract, unshown, for the
  place filter to come.

## Consequences

- `GODOC_URL` is a new setting in both `.env.example` files and the dev
  compose file. Locally the server is started by hand from `godoc/.venv`
  and nothing restarts it after a reboot (context/integrations/godoc.md).
- The `airports` dataset — where the only four cards live today — has no
  asset with an extent, so `dataset_bbox` is null for every live match
  until the data platform gives that dataset coverage.
- A sequential scan over the cards is fine at this size; the data platform
  adds an ANN index per embedder when the table earns it. Changing the
  embedder means re-embedding the cards, and the portal follows
  automatically: it filters on whatever model the server names.
- Not here: narrowing the matches to a place (the dataset's extent is the
  obvious handle), the chunk-level search for a passage, and opening a
  PDF at the page a chunk is on (docs/adr/017).
