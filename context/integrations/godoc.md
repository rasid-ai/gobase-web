# GoDoc — the data platform's document service, used to embed a question

GoDoc is the data platform's document parser and RAG server (the `godoc`
repo beside `gobase`). Its `serve-rag` server parses PDFs into the bundles
the catalog ingests, and holds the embedding model that made every card in
`doc_cards`. The portal uses it for one thing: turning the map's Semantic
question into a vector with that same model (docs/adr/018).

Only `backend/apps/catalog/godoc.py` speaks to it. Everything above that
module handles a question in and a `(model, vector)` out, and would not
change if the embedding moved elsewhere. The frontend never reaches it; it
calls `GET /api/catalog/assets/similar` like any other portal endpoint.

Read on 2026-10-19 against GoDoc 0.1.0 on this laptop.

## Connecting

`POST {GODOC_URL}/rag/embed`, one call per question. Request
`{"texts": ["<the question>"]}`; answer
`{"model": "BAAI/bge-small-en-v1.5", "dim": 384, "normalized": true,
"vectors": [[…384 floats…]]}`. No authentication. A body it will not take
is 400; more than 2048 texts is 413.

| Setting | Local default | What it is |
|---|---|---|
| `GODOC_URL` | `http://127.0.0.1:8003` in `backend/.env.example`; blank in `infra/.env.example` | The server root. `/rag/embed` is appended. **Blank is a supported state**: the endpoint answers 503 and the pane says semantic search is unavailable. |
| `GODOC_TIMEOUT_SECONDS` | `10` | Per-request timeout. A query embeds in well under a second on CPU; the margin is for a cold server. |

`GET {GODOC_URL}/health` says which model is loaded, its dimension, whether
it normalises, and the device — the quickest way to check the server is up
and is the model the cards were made with.

The server's other routes (`/rag/jobs`, `/pipeline`, the bundle download)
are the data platform's ingest path and the portal never calls them.

## The model has to match the cards

`doc_cards.embedder_id` names the model that made each card; the portal
filters the search on the `model` the embed answer names, so a card made by
another model is never ranked against a vector it cannot be compared with.
The data platform's own search does not check this. If the server is
started with a different `--model` than the cards were made with, the
search answers an empty list rather than nonsense — and the fix is on the
data platform's side (re-embed, or start the right model).

No instruction prefix is sent, for a query or anywhere else: the cards were
embedded as plain text, and a query embedded differently from its corpus
ranks worse. The vectors are unit length, so cosine distance (`<=>`) is the
right operator and gives the data platform's own ranking.

## Running it locally

The server is started by hand from `godoc/.venv` and nothing restarts it
after a reboot:

```bash
cd ~/Desktop/alidb/Rasid/godoc && .venv/bin/godoc serve-rag   # 127.0.0.1:8003
```

It refuses ports 8000 and 8002 (Django's and the MinerU router's). It
loads the model once at startup; CPU is enough for a query, the GPU only
matters for parsing. The VPS runs it as the data platform's `godoc-rag`
container, CPU only, with the same model.

## Failures

Two exceptions in `godoc.py`, and the distinction decides the status code:

- `GoDocUnavailable` → **503**. Timeout, refused, DNS, HTTP 5xx, or a body
  that is not JSON. Try again later; the question is not the problem.
- `GoDocError` → **502**. HTTP 4xx, or an answer with no model or no vector.
  The server is up and saying no.

The exception carries the httpx type name, never its message: an httpx
message can quote the request, and the question is chat content that stays
out of application logs (CLAUDE.md).
