"""The only module that reads the lake.

Everything above this speaks GeoJSON. The lake is S3-compatible object storage
holding GeoParquet written by the data platform; the catalog gives the URI and
this module turns the file behind it into features (docs/adr/008).

DuckDB rather than a Python GeoParquet reader: it pushes the area filter and
the row cap down into the scan, so a file is never fully materialised to return
the part of it the map can see, and `ST_AsGeoJSON` does the geometry conversion
in C++.

DuckDB reads the lake; it never touches Postgres. `kb` stays on Django's
connection and its read-only role (docs/adr/002).
"""

import json
import logging
import threading

import duckdb
from django.conf import settings

logger = logging.getLogger(__name__)


class LakeUnavailable(Exception):
    """The lake could not be reached: refused, unresolved, or not authorised."""


class LakeReadError(Exception):
    """The lake answered, but the file is missing or not readable as GeoParquet."""


# One connection per worker process, built on first use. DuckDB connections are
# thread-safe for cursors but not for setup, so the lock covers creation only.
_connection = None
_lock = threading.Lock()

# URIs already reported as having no covering column, so the warning is not
# repeated on every pan. Bounded by the number of vector assets.
_warned_uncovered: set[str] = set()

# Substrings that mark a failure as "could not reach the lake" rather than
# "could not read the file". DuckDB reports both as IOException, so the message
# is the only thing separating a dead endpoint from a bad path.
_UNAVAILABLE_MARKERS = (
    "connection error",
    "could not connect",
    "could not establish connection",
    "connection refused",
    "timeout",
    "timed out",
    "name or service not known",
    "temporary failure in name resolution",
    "http 401",
    "http 403",
    "access denied",
    "invalidaccesskeyid",
    "signaturedoesnotmatch",
)


# The name the data platform gives the GeoParquet 1.1 covering column. Both
# repos hardcode it; see `_covering_bbox_column`.
COVERING_BBOX = "bbox"


def _sql_literal(value: str) -> str:
    """Quote a configuration value for a statement that cannot bind parameters."""
    return "'" + str(value).replace("'", "''") + "'"


def _secret_statement() -> str | None:
    """The CREATE SECRET for the configured object store, or None if there is none.

    None is a real answer, not a failure: with no endpoint, no region and no
    credentials there is nothing to point at, and the only thing readable is a
    local path, which needs no secret at all. That is the case in tests and in
    CI, and creating a secret there would drag in an extension for no benefit.

    Built as text because CREATE SECRET takes no bound parameters. Kept separate
    from executing it so it can be tested without DuckDB, a network, or an
    extension download.
    """
    has_keys = bool(settings.LAKE_S3_ACCESS_KEY and settings.LAKE_S3_SECRET_KEY)
    if not (has_keys or settings.LAKE_S3_ENDPOINT or settings.LAKE_S3_REGION):
        return None

    fields = ["TYPE s3"]
    if has_keys:
        fields.append(f"KEY_ID {_sql_literal(settings.LAKE_S3_ACCESS_KEY)}")
        fields.append(f"SECRET {_sql_literal(settings.LAKE_S3_SECRET_KEY)}")
    else:
        # Configured but without static keys: an instance role supplies them
        # through DuckDB's credential chain.
        fields.append("PROVIDER credential_chain")

    if settings.LAKE_S3_ENDPOINT:
        fields.append(f"ENDPOINT {_sql_literal(settings.LAKE_S3_ENDPOINT)}")
    # AWS needs the bucket's region; MinIO and RustFS ignore it, so a blank one
    # is simply omitted rather than sent as an empty string.
    if settings.LAKE_S3_REGION:
        fields.append(f"REGION {_sql_literal(settings.LAKE_S3_REGION)}")
    fields.append(f"URL_STYLE {_sql_literal(settings.LAKE_S3_URL_STYLE)}")
    fields.append(f"USE_SSL {'true' if settings.LAKE_S3_USE_SSL else 'false'}")

    return f"CREATE OR REPLACE SECRET lake ({', '.join(fields)})"


def _configure(connection) -> None:
    """Point a fresh connection at the configured object store.

    A SECRET, not `SET s3_*`. The legacy settings are session-scoped, and
    `connection.cursor()` — which every request uses — opens its own session
    and does not inherit them, so the store is reached with no configuration at
    all and answers 404, which reads exactly like a missing file. A secret
    lives in the database, so every cursor shares it.

    No provider is named here. RustFS, MinIO and AWS differ only in the values
    below, which is why they live in .env (infra/README.md).
    """
    connection.execute("INSTALL httpfs; LOAD httpfs;")
    connection.execute("INSTALL spatial; LOAD spatial;")

    statement = _secret_statement()
    if statement is None:
        return

    # `credential_chain` is implemented by the `aws` extension rather than
    # httpfs, and is not bundled. Loading it explicitly rather than relying on
    # autoload, which needs a network round trip the first time and fails on a
    # machine that has never fetched it.
    if "credential_chain" in statement:
        connection.execute("INSTALL aws; LOAD aws;")

    try:
        connection.execute(statement)
    except duckdb.Error as exc:
        # The statement carries the secret key, so it must never reach a log or
        # an exception message. Only the failure type is reportable.
        raise LakeUnavailable(f"Could not configure lake access: {type(exc).__name__}") from None


def _shared_connection():
    """The process-wide connection, created on first use."""
    global _connection
    if _connection is None:
        with _lock:
            if _connection is None:
                connection = duckdb.connect(":memory:")
                _configure(connection)
                _connection = connection
    return _connection


def reset() -> None:
    """Drop the shared connection so the next call rebuilds it.

    Tests change the lake settings between cases; without this they would keep
    talking to a connection configured for the previous case.
    """
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
        _connection = None
        _warned_uncovered.clear()


def _geometry_column(cursor, uri: str) -> str:
    """The name of the geometry column in a GeoParquet file.

    Read from the file rather than assumed. The catalog's `geo_layers.columns`
    lists attribute columns only and does not include the geometry, and it does
    carry a text attribute called `geomtype` that a name guess would match by
    mistake (context/integrations/kb.md).

    GeoParquet records the geometry column in its file metadata under
    `geo`. Falling back to a BLOB column covers a file written without that
    metadata, which DuckDB's spatial extension still reads.
    """
    cursor.execute(
        "SELECT decode(value) FROM parquet_kv_metadata(?) WHERE decode(key) = 'geo'",
        [uri],
    )
    row = cursor.fetchone()
    if row and row[0]:
        try:
            meta = json.loads(row[0])
            column = meta.get("primary_column")
            if column:
                return column
        except (ValueError, TypeError):
            logger.warning("Unreadable GeoParquet `geo` metadata in %s", uri)

    cursor.execute(
        "SELECT name FROM parquet_schema(?) WHERE type = 'BYTE_ARRAY' LIMIT 1",
        [uri],
    )
    row = cursor.fetchone()
    if not row:
        raise LakeReadError(f"No geometry column found in {uri}")
    return row[0]


def _covering_bbox_column(cursor, uri: str) -> str | None:
    """The GeoParquet 1.1 covering column, or None if the file has none.

    One box per feature, derived from the geometry. It exists for readers to
    prune with, so it is a filter and never a property.

    Detected by name and type rather than from the `geo` metadata's `covering`
    key, because the same rule has to match a file DuckDB wrote — `COPY` emits
    the column but not that metadata. `gobase/cli/export.py:is_covering_bbox`
    is the other half of this agreement and tests exactly the same thing; the
    two must not drift.
    """
    cursor.execute("DESCRIBE SELECT * FROM read_parquet(?)", [uri])
    for name, dtype, *_ in cursor.fetchall():
        if name == COVERING_BBOX and str(dtype).upper().startswith("STRUCT(XMIN"):
            return name

    # Every silver file is supposed to have one. A file without it still reads
    # correctly — it just reads the whole file to answer an area query — so
    # this is a defect to report, not a failure to raise. Once per URI, since
    # the alternative is a line per pan per layer.
    if uri not in _warned_uncovered:
        _warned_uncovered.add(uri)
        logger.warning(
            "No `%s` covering column in %s: area queries read the whole file. "
            "Silver writes one for every vector asset, so this file predates "
            "that or was written by something else.",
            COVERING_BBOX,
            uri,
        )
    return None


def _jsonable(value):
    """Coerce a Parquet value into something JSON can hold.

    Properties come from whatever columns the file has, so the types are not
    known ahead of time: timestamps, dates, decimals and UUIDs all arrive as
    Python objects that json cannot serialise.
    """
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", "replace")
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def read_vector_features(
    uri: str,
    *,
    limit: int,
    bbox: tuple[float, float, float, float] | None = None,
    cursor: int | None = None,
) -> dict:
    """Read one page of features from a GeoParquet file in the lake.

    `bbox` is `(min_lon, min_lat, max_lon, max_lat)` in SRID 4326. It keeps the
    read to the area the caller asked about; without it the whole file is in
    scope. It matches on bounding boxes, so it is slightly over-inclusive — see
    the filter below. `cursor` is the `next_cursor` the previous page returned.

    Returns the features, how many this page holds, and the cursor for the next
    page — None when this page is the last. The scan asks for one row beyond
    the page so a page that exactly fills `limit` is not reported as having
    more behind it.

    Paging is keyset on `file_row_number` rather than by offset. `read_parquet`
    has no inherent order and DuckDB scans in parallel, so an offset would
    repeat some rows and skip others between pages (the same hazard
    `catalog/kb.py` documents for the asset list). Ordering by the file's own
    row number makes the sequence stable and makes the next page a range scan
    rather than a re-read.
    """
    try:
        reader = _shared_connection().cursor()
    except duckdb.Error as exc:
        raise LakeUnavailable(str(exc)) from exc

    try:
        geometry = _quote(_geometry_column(reader, uri))
        covering = _covering_bbox_column(reader, uri)

        # Both filters are optional and each binds its own parameters, so the
        # WHERE clause is assembled rather than written out.
        conditions: list[str] = []
        params: list = [uri]
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            if covering is not None:
                # A plain range test on the covering column, and the whole
                # reason the area filter is affordable. DuckDB checks it
                # against each row group's min/max statistics and skips the
                # groups that miss, before reading any geometry at all. It
                # will not derive this from ST_Intersects_Extent on its own
                # (checked on DuckDB 1.5.5), so without it every row of the
                # file is read off the object store to answer any area query.
                box = _quote(covering)
                conditions.append(
                    f"{box}.xmin <= ? AND {box}.xmax >= ? AND {box}.ymin <= ? AND {box}.ymax >= ?"
                )
                params.extend([max_lon, min_lon, max_lat, min_lat])

            # Then the exact-ish test, on whatever survived. Bounding boxes
            # again, not real geometry: `ST_Intersects_Extent` is a
            # box-against-box test and the exact predicate does real geometry
            # work on every surviving row, measured 18-40% slower for the same
            # rows.
            #
            # It is over-inclusive and never under-inclusive: a feature whose
            # box overlaps the area but whose geometry does not comes back too.
            # For drawing that is free — it lands off screen and MapLibre clips
            # it. Anything counting or answering from this must know it
            # (docs/adr/012).
            conditions.append(f"ST_Intersects_Extent({geometry}, ST_MakeEnvelope(?, ?, ?, ?))")
            params.extend(bbox)
        if cursor is not None:
            conditions.append("file_row_number > ?")
            params.append(cursor)
        where = f"WHERE {' AND '.join(conditions)} " if conditions else ""

        # The geometry column, the row number and the covering box are all
        # excluded from the star so none of them can also appear as a property;
        # every remaining column becomes one. The covering box is derived from
        # the geometry and is there to filter with, so it is not the file's
        # data and must not reach the map.
        internal = [geometry, "file_row_number"]
        if covering is not None:
            internal.append(_quote(covering))

        reader.execute(
            f"SELECT ST_AsGeoJSON({geometry}) AS __geometry__, "
            f"file_row_number AS __cursor__, "
            f"* EXCLUDE ({', '.join(internal)}) "
            f"FROM read_parquet(?, file_row_number = true) "
            f"{where}"
            f"ORDER BY file_row_number "
            f"LIMIT {int(limit) + 1}",
            params,
        )
        columns = [column[0] for column in reader.description]
        rows = reader.fetchall()
    except duckdb.Error as exc:
        raise _classify(exc, uri) from exc
    finally:
        reader.close()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = int(page[-1][columns.index("__cursor__")]) if has_more and page else None
    features = [_feature(columns, row) for row in page]
    return {"count": len(features), "next_cursor": next_cursor, "features": features}


def _feature(columns: list[str], row: tuple) -> dict:
    """One GeoJSON Feature from a result row."""
    values = dict(zip(columns, row, strict=True))
    geometry = values.pop("__geometry__", None)
    # The paging key is bookkeeping, not one of the file's columns.
    values.pop("__cursor__", None)
    return {
        "type": "Feature",
        "geometry": json.loads(geometry) if geometry else None,
        "properties": {key: _jsonable(value) for key, value in values.items()},
    }


def _quote(identifier: str) -> str:
    """Quote a column name read from a file, which cannot be a bound parameter."""
    return '"' + identifier.replace('"', '""') + '"'


def _classify(exc: Exception, uri: str) -> Exception:
    """Decide whether a DuckDB failure means the lake is down or the file is bad.

    DuckDB raises IOException for both, so the message is all there is to go on.
    Unreachable and unauthorised are 503 (try again later); anything else is a
    502, because the lake answered and the file is the problem.
    """
    message = str(exc).lower()
    if any(marker in message for marker in _UNAVAILABLE_MARKERS):
        logger.warning("Lake unreachable while reading %s: %s", uri, exc)
        return LakeUnavailable(str(exc))
    logger.warning("Unreadable lake object %s: %s", uri, exc)
    return LakeReadError(str(exc))
