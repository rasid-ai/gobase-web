# ADR-020: Deep search reads the chunk index, and shows the page it matched on

**Status:** Accepted · 2026-10-27
**Builds on:** docs/adr/017 (the PDF served whole from bronze), docs/adr/018
(the shallow search over cards), docs/adr/019 (one search kind at a time)

## Context

The map's Semantic mode finds **documents**: one card per PDF in
`kb.doc_cards`, ranked by cosine (ADR-018). It cannot say which passage
matched, and the Assets page had no search by meaning at all.

The data platform also writes a **chunk index**: one LanceDB table per
embedding model on the silver bucket
(`s3://geobase-silver/index/chunks/<embedder>.lance`), one row per passage
with its text, section headings, pages (from 0) and the boxes it occupies on
the page, on MinerU's 0..1000 grid (context/integrations/lance.md).
`doc_documents.chunks_uri` names the table. Nothing in the portal read it.

What the two services serve today, checked by reading both repos:

- GoDoc `serve-rag` embeds text (`POST /rag/embed`). It has no search route
  and renders no pages.
- GoBase serves nothing over the network for search. Its docs say, three
  times, that GoBase-Web runs the same two steps itself: ask Postgres for the
  documents in scope, then the table for the nearest passages among them.
  `gobase/modalities/document/store.py::search_chunks` is the reference.
- GoDoc's demo (`demo/gobase_demo_server.py`) draws a passage's boxes on a
  page rendered with pypdfium2. A demo over local files, not a service.

Ali asked for a third search kind on the Assets page that finds passages and
opens the PDF at the matched one, combinable with a place and the other
filters but not with the metadata search.

## Decision

### The portal reads the chunk index itself

`lancedb` joins the backend; `apps/catalog/chunks.py` is the only module that
imports it, on first use. The search is the data platform's own two steps:

1. **The shortlist, in Postgres.** `kb.chunked_documents` is the browse CTE
   joined to `doc_documents`, so the place (by the datasets' coverage), the
   ingestion window and the open dataset narrow it exactly as they narrow the
   list — and filtered on `embedder_id = <the model GoDoc named>`, so a table
   made by another model is never searched with this vector. A mismatch is an
   empty answer, not nonsense and not an error.
2. **The passages, in Lance.** Nearest-neighbour by cosine with
   `asset_id IN (...)` as a prefilter, `limit × passages` rows in all, then
   grouped by document, best passage first, cut to `limit` documents. A row
   of a document not in the shortlist is skipped: the table has held rows of
   a catalog that no longer existed (gobase diary, 2026-10-19).

The question is embedded by `godoc.embed`, as the card search does. The
read-only `LAKE_S3_*` settings open the table, the same credentials DuckDB
reads GeoParquet with.

**`GET /api/catalog/passages?q=&limit=&passages=&dataset=&bbox=&coverage=…`**
answers with documents, each a list row plus its matching passages: text,
heading path, pages **from 1**, the pages that carry boxes, the chunk type.
Pages are converted once, in `passages.py`; the index's 0-based numbers
never leave the server. The score is in the contract and not on the screen
(ADR-018).

### The page is rendered on the server, with the passage drawn on it

**`GET /api/catalog/assets/{id}/pages/{page}.png?chunk=`** reads the PDF from
bronze through the lake (ADR-017), renders that page with pypdfium2 and draws
the passage's boxes with Pillow: `apps/catalog/pages.py`, the only module
that imports either. The highlight is the brand emerald, written into the
module because a design token cannot reach an image drawn on the server.

The ETag is the PDF's hash, the chunk, the page and the renderer's version,
so a revalidation costs a catalog lookup and neither a lake read nor a
render. The browser fetches the image with the session, like the PDF, since
an `<img src>` cannot carry the token; and only once a passage is opened,
so no page is rendered for a row nobody looked at.

**Open PDF at the page**: the existing opener appends `#page=N` to the
object URL, which every browser's viewer honours.

### On the page

Semantic is the third kind in the search box's switch. It is asked on
submit, never as typed. A question replaces the grid, in both browse modes,
with the documents whose passages answer it; the dataset cards come back
when the question is removed. It combines with the place, the window and the
open dataset; it never stands beside a metadata search, which shares the
box — choosing one clears the other. The data type filter is hidden while a
question is active, because only documents have passages. Switching mode
clears it like every filter (ADR-019).

## Rejected

**A search route in GoDoc or GoBase, called by the portal.** Neither has
one. GoDoc knows nothing of the catalog; GoBase would need a server it does
not run. And the place, the window and the dataset are catalog questions the
portal already answers — a remote search would have to grow them all again.

**A copy of the chunks in Postgres.** `kb` is not ours to write (ADR-002).

**DuckDB over the table.** It reads the lake already, but has no vector
search.

**Opening the PDF at the page only.** Cheap, but nothing then marks the
passage, and a reader scans the page to find it. The boxes are in the index
already; drawing them costs one render.

**A reranker, paged passages, word highlighting in the excerpt.** Later,
if the ranking or the volume asks for them.

## Consequences

- `lancedb` brings `pyarrow`; the backend image grows by roughly 350 MB.
  The import is lazy, so start-up and tests that never search pay nothing.
- pdfium is not thread-safe: renders run under one lock per process. A page
  renders in well under a second; a cold Lance connection cost the first
  search ~3 s locally.
- The question travels in the request line, as the place search and the
  card search do (ADR-018). The portal never logs it.
- A document whose `chunks_uri` is null, or whose table is not in the
  bucket, is never in deep results. The data platform's next run rebuilds
  the index.
- `airports` is the only dataset with documents today, and no file in it has
  coverage: a question with any place answers nothing until the data
  platform gives such datasets a footprint (ADR-019).

## Revisit when

A table outgrows a flat scan (the data platform then adds an ANN index);
the ranking wants a reranker; or GoBase grows a search service, at which
point the portal would call it instead of reading the table.
