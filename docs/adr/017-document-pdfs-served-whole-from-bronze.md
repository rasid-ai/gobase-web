# ADR-017: A document is named after its PDF, and the PDF is served whole from bronze

**Status:** Accepted · 2026-10-19

## Context

The data platform now parses PDFs. In `kb` each one is an `assets` row with
`modality = 'document'`, whose `source_uri` is the parsed bundle it wrote to
silver — `…/documents/airports/<stem>.bundle.zip` — and a `doc_documents` row
that names the original PDF in bronze (`pdf_uri`), with its title and page
count (context/integrations/kb.md). The Assets page named every asset after
its source path, so a document showed as `<stem>.bundle`, and nothing could
open it.

Two rules already decide most of the design. The browser never talks to S3;
anything carrying a credential goes through the backend (docs/adr/011). And
every API call carries a bearer token, so a plain link to a backend URL
cannot open a file: the browser would send no token and get a 401.

The user asked for the PDFs to be named as PDFs and to open in a new browser
tab. Opening at a page or a passage, and searching documents, come later.

## Decision

- **A document is named after its PDF, extension kept.** The name is
  `COALESCE(basename(doc.pdf_uri), <derived name without .bundle>)`, computed
  in SQL beside the derived name so display, search and sort still agree
  (docs/adr/010). The parser's title is a second line, not the name: on the
  four live documents it is "1. Introduction" and worse.
- **Its format is its file's, `pdf`**, taken from the PDF name's extension,
  not the parser `assets.format` records (`mineru`). A reader is told what
  the thing is; which parser read it is detail, and the detail carries it as
  `parser`.
- **Every catalog read LEFT JOINs `doc_documents`.** The browse list gains
  one nullable field, `document: {title, pages, pdf}`, null for every other
  data type. A `kb` without the table fails the Assets page, so the two repos
  deploy together — the rule `dataset` already set (docs/adr/016).
- **`GET /api/catalog/assets/{id}/pdf` serves the bytes.** The backend
  resolves `pdf_uri`, reads the object with DuckDB's `read_blob` through the
  lake secret it already holds, and answers `application/pdf`, inline, named
  after the file. No presigned URL: the browser would then fetch from the
  bucket, which docs/adr/011 forbids. No new dependency: DuckDB can read a
  blob, and the PDFs are hundreds of kilobytes.
- **Whole, not streamed, and not compressed.** `read_blob` has no streaming
  form and a PDF is already compressed. The day a multi-gigabyte object has
  to be served is the day a streaming S3 client earns a place in
  requirements; not before.
- **The ETag is `assets.content_hash`**, which for a document is the PDF's
  own sha256. A strong tag for free, and a revalidation costs a catalog
  lookup and never a lake read. `Cache-Control: private, no-cache`, as the
  features endpoint (docs/adr/015).
- **The client opens a tab first, then fetches.** `window.open('', '_blank')`
  inside the click, which popup blockers allow; then the bytes with the
  session, wrapped in an object URL the tab is pointed at. The blob keeps its
  type, so the browser's own viewer shows it. A failed fetch closes the tab
  and the card says so in place.
- **Open PDF is offered only when `pdf` is true.** A bundle loaded without
  its source stamp has no `pdf_uri`; it gets no button rather than one that
  fails.

## Consequences

- `apps/map/lake.py` reads bronze as well as silver now; the one set of
  `LAKE_S3_*` credentials covers both (context/integrations/lake.md).
- The two lake-backed views share `LakeUnreachable`, `LakeFailed` and
  `cacheable` from `apps/map/http.py`, so a dead lake answers 503 and a bad
  object 502 from either.
- `pdf_uri` can be stale after a move in bronze until the data platform's
  next reindex, on purpose on its side. The endpoint then answers 502; the
  bundle's `x-amz-meta-source-uri` is the current path if that ever needs
  handling here.
- `fetchWithSession` in `frontend/src/api/http-client.ts` is the raw
  authenticated fetch; `httpClient` is that plus JSON. Anything else that
  needs bytes rather than JSON goes through it.
- Opening at a page is one line away: the chunk index records `page_start`
  per passage, and `#page=N` on the object URL is honoured by every
  browser's viewer. Opening at a line is not possible with this data —
  nothing records lines, only bounding boxes on a 0..1000 grid per passage.
