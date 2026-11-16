# The chunk index — LanceDB on the silver bucket, read for deep search

The data platform parses each PDF into passages ("chunks"), embeds them, and
writes them with their vectors to one LanceDB table per embedding model on
the silver bucket. The portal reads that table to find the passages nearest a
question (docs/adr/020). It never writes it.

Read on 2026-10-27 against lancedb 0.40.0 and the local MinIO.

## What talks to it

`backend/apps/catalog/chunks.py`, and nothing else. It is the only module
that imports `lancedb`, and it imports it on first use: the wheel is large and
nothing at start-up needs it. `apps/catalog/passages.py` joins its answer to
the catalog's; everything above speaks in documents and passages.

## Where the table is

`doc_documents.chunks_uri` names it per document
(context/integrations/kb.md):

```
s3://geobase-silver/index/chunks/BAAI_bge-small-en-v1.5.lance
```

The directory is the store, the last path piece (without `.lance`) the table.
There is one table per embedder; a new model is a new table beside the old.
Locally, on 2026-10-27: 29 rows from 4 documents.

## The columns

Pinned by the data platform (`gobase/tests/test_document_lance.py`):

| column | type | meaning |
|---|---|---|
| `chunk_id` | string | GoDoc's stable id, 32 hex characters |
| `asset_id` | string | the `assets` row; the prefilter key |
| `doc_id` | string | the PDF's sha256 |
| `ord` | int32 | the passage's order in the document |
| `text` | string | the passage |
| `token_count` | int32 | |
| `chunk_type` | string | text, table, list, chart, image, … |
| `heading_path` | list<string> | the section headings above it, outermost first |
| `page_start`, `page_end` | int32 | **from 0**, MinerU's numbering; null for plain text |
| `bboxes` | string | JSON `[{"page": 0, "bbox": [x0, y0, x1, y1]}, …]` on MinerU's **0..1000 grid** per page |
| `vector` | fixed_size_list<float32>[dim] | unit length; cosine distance |

The portal turns pages into reader's numbers (from 1) once, in
`passages.py`, and parses `bboxes` into a list in `chunks.py`; a value that
is not that shape is "no boxes", never a failure.

## Connecting

`chunks.storage_options()` builds lancedb's `storage_options` from the same
settings DuckDB reads the lake with (context/integrations/lake.md):

| setting | becomes |
|---|---|
| `LAKE_S3_ENDPOINT` set | `aws_endpoint` = `http://` or `https://` + endpoint (by `LAKE_S3_USE_SSL`) |
| `LAKE_S3_URL_STYLE=path` | `aws_virtual_hosted_style_request=false` |
| `LAKE_S3_USE_SSL=false` | `allow_http=true` |
| `LAKE_S3_REGION` set | `aws_region` |
| both keys set | `aws_access_key_id`, `aws_secret_access_key` |
| nothing set | `None`: the ambient AWS credentials, as DuckDB's credential chain |

A blank region works against MinIO. The keys are passed and never logged;
an object_store message can quote the endpoint and the key id, so every
failure travels as its exception's type name only.

One connection per store directory, built on first use under a lock;
`chunks.reset()` drops them (tests). The first search after a start pays
the connection: ~3 s locally.

## Reading

`chunks.search(chunks_uri, vector, asset_ids, k)`:

```python
table.search(vector, vector_column_name="vector")
     .distance_type("cosine")
     .where("asset_id IN ('…', '…')", prefilter=True)
     .limit(k).to_list()
```

`score = 1 - _distance`; `vector` is dropped. Empty `asset_ids` is an empty
answer without a connection. A table the catalog names but the bucket does
not hold (lancedb raises `ValueError: Table '…' was not found`) is an empty
answer too: the data platform's next run rewrites it.

`chunks.chunk(chunks_uri, asset_id, chunk_id)` fetches one passage, filtered
on both ids so a URL cannot read across documents. Two endpoints use it: the
page image, for the passage's boxes, and `GET
/api/catalog/assets/{id}/passages/{chunk_id}`, which returns the passage's
text, headings and pages for the Ask agent's `doc_read` tool (docs/adr/024).
Both values are quoted into the filter; `chunk_id` is also checked against
`CHUNK_ID_PATTERN` (`apps/catalog/serializers.py`) before it gets here.

No ANN index exists; a flat scan is milliseconds at this size.

## Failures

- `ChunkStoreUnavailable` → **503**: the store could not be reached, or
  refused. Try again later.
- `ChunkStoreError` → **502**: the table answered and the search failed.

## Checking it locally

```bash
cd backend && .venv/bin/python manage.py shell -c "
from apps.catalog import chunks
print(chunks.search('s3://geobase-silver/index/chunks/BAAI_bge-small-en-v1.5.lance',
                    [0.0]*384, ['<an asset_id from doc_documents>'], k=1))"
```

MinIO must be running (`docker start minio`), and `GODOC_URL` must reach a
`serve-rag` started with `--model BAAI/bge-small-en-v1.5` for a real question
to be embedded (context/integrations/godoc.md).
