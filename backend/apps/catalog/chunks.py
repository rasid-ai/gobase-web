"""The only module that reads the chunk index.

The data platform parses each PDF into passages and writes them, with their
vectors, to one LanceDB table per embedding model on the silver bucket
(context/integrations/lance.md). The catalog names the table in
`doc_documents.chunks_uri`; this module opens it and finds the passages nearest
a vector, within the documents a caller names (docs/adr/020). It is a port of
the data platform's own reader, `gobase/modalities/document/lance.py`.

It reads with the lake's read-only credentials and never writes. `lancedb` is
imported on first use, not at import: the wheel is large, and neither start-up
nor a test that never searches should pay for it.
"""

import json
import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)


class ChunkStoreUnavailable(Exception):
    """The table could not be reached: the store is down, refused, or unauthorised."""


class ChunkStoreError(Exception):
    """The table answered, but the search itself failed."""


# One connection per table directory, built on first use. The lock covers
# creation only; lancedb connections are safe to share afterwards.
_connections: dict[str, object] = {}
_lock = threading.Lock()


def storage_options() -> dict[str, str] | None:
    """What object_store needs to reach the lake, from the same settings DuckDB uses.

    None when nothing is configured: lancedb then falls back to the ambient AWS
    credentials, as DuckDB's credential chain does (context/integrations/lake.md).
    The keys, when set, are passed and never logged.
    """
    options: dict[str, str] = {}
    endpoint = settings.LAKE_S3_ENDPOINT
    if endpoint:
        scheme = "https://" if settings.LAKE_S3_USE_SSL else "http://"
        options["aws_endpoint"] = scheme + endpoint
        if settings.LAKE_S3_URL_STYLE == "path":
            options["aws_virtual_hosted_style_request"] = "false"
        if not settings.LAKE_S3_USE_SSL:
            options["allow_http"] = "true"
    if settings.LAKE_S3_REGION:
        options["aws_region"] = settings.LAKE_S3_REGION
    if settings.LAKE_S3_ACCESS_KEY and settings.LAKE_S3_SECRET_KEY:
        options["aws_access_key_id"] = settings.LAKE_S3_ACCESS_KEY
        options["aws_secret_access_key"] = settings.LAKE_S3_SECRET_KEY
    return options or None


def table_location(chunks_uri: str) -> tuple[str, str]:
    """The directory holding the tables, and this table's name, from its URI.

    `s3://bucket/index/chunks/BAAI_bge-small-en-v1.5.lance` is the directory
    `s3://bucket/index/chunks` and the table `BAAI_bge-small-en-v1.5`: lancedb
    opens a directory and names tables within it.
    """
    directory, _, name = chunks_uri.rstrip("/").rpartition("/")
    return directory, name.removesuffix(".lance")


def search(chunks_uri: str, vector, asset_ids, k: int) -> list[dict]:
    """The `k` passages nearest `vector` among the documents in `asset_ids`, best first.

    An empty `asset_ids` is an empty answer without a connection: there is
    nothing to look in. A table the catalog names but the bucket does not hold
    is an empty answer too, not a failure — the index is rebuilt by the data
    platform's next run.
    """
    ids = [str(asset_id) for asset_id in asset_ids]
    if not ids:
        return []
    table = _open(chunks_uri)
    if table is None:
        return []
    try:
        hits = (
            table.search(list(vector), vector_column_name="vector")
            .distance_type("cosine")
            .where(f"asset_id IN ({_sql_list(ids)})", prefilter=True)
            .limit(k)
            .to_list()
        )
    except Exception as exc:
        raise ChunkStoreError(type(exc).__name__) from exc
    return [_hit(hit) for hit in hits]


def chunk(chunks_uri: str, asset_id, chunk_id: str) -> dict | None:
    """One passage by its id, within its document, or None if there is no such row."""
    table = _open(chunks_uri)
    if table is None:
        return None
    try:
        rows = (
            table.search()
            .where(f"asset_id = {_sql_text(str(asset_id))} AND chunk_id = {_sql_text(chunk_id)}")
            .limit(1)
            .to_list()
        )
    except Exception as exc:
        raise ChunkStoreError(type(exc).__name__) from exc
    return _hit(rows[0]) if rows else None


def reset() -> None:
    """Drop every connection, so the next read builds one from the current settings."""
    with _lock:
        _connections.clear()


def _open(chunks_uri: str):
    """The table behind a `chunks_uri`, or None if the directory does not hold it."""
    directory, name = table_location(chunks_uri)
    database = _connect(directory)
    try:
        return database.open_table(name)
    except ValueError as exc:
        # lancedb says "Table 'x' was not found" as a ValueError. Any other
        # ValueError from opening is not a search problem either.
        logger.warning("Chunk table %s not found in %s: %s", name, directory, type(exc).__name__)
        return None
    except Exception as exc:
        raise ChunkStoreUnavailable(type(exc).__name__) from exc


def _connect(directory: str):
    with _lock:
        database = _connections.get(directory)
        if database is None:
            import lancedb

            try:
                database = lancedb.connect(directory, storage_options=storage_options())
            except Exception as exc:
                # The type only: an object_store message can quote the
                # endpoint and the key id.
                raise ChunkStoreUnavailable(type(exc).__name__) from exc
            _connections[directory] = database
        return database


def _hit(row: dict) -> dict:
    """A table row in portal terms: a score instead of a distance, boxes parsed, no vector."""
    hit = dict(row)
    hit.pop("vector", None)
    distance = hit.pop("_distance", None)
    hit["score"] = 1.0 - float(distance) if distance is not None else None
    hit["bboxes"] = _boxes(hit.get("bboxes"), hit.get("chunk_id"))
    return hit


def _boxes(raw, chunk_id) -> list[dict]:
    """The passage's boxes, `[{"page": int, "bbox": [x0, y0, x1, y1]}, ...]`, or none.

    Stored as JSON text on MinerU's 0..1000 grid (context/integrations/lance.md).
    A value that does not parse as that shape is no boxes, not a failure: the
    passage is still a match, it just cannot be drawn.
    """
    if not raw:
        return []
    try:
        boxes = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        logger.warning("Unreadable boxes on chunk %s", chunk_id)
        return []
    if not isinstance(boxes, list):
        return []
    return [
        box
        for box in boxes
        if isinstance(box, dict)
        and isinstance(box.get("page"), int)
        and isinstance(box.get("bbox"), list)
        and len(box["bbox"]) == 4
    ]


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_list(values) -> str:
    return ", ".join(_sql_text(str(value)) for value in values)
