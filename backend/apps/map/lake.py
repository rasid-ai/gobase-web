"""The only module that reads the lake.

Everything above this speaks GeoJSON. The lake is S3-compatible object storage
holding GeoParquet written by the data platform; the catalog gives the URI and
this module turns the file behind it into features (docs/adr/008).

DuckDB rather than a Python GeoParquet reader: it pushes the row cap down into
the scan, so a 10,000-feature file is never fully materialised to return 5,000
of them, and `ST_AsGeoJSON` does the geometry conversion in C++.

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


def _sql_literal(value: str) -> str:
    """Quote a configuration value for a statement that cannot bind parameters."""
    return "'" + str(value).replace("'", "''") + "'"


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

    fields = ["TYPE s3"]
    if settings.LAKE_S3_ACCESS_KEY and settings.LAKE_S3_SECRET_KEY:
        fields.append(f"KEY_ID {_sql_literal(settings.LAKE_S3_ACCESS_KEY)}")
        fields.append(f"SECRET {_sql_literal(settings.LAKE_S3_SECRET_KEY)}")
    else:
        # No static keys is deliberate: DuckDB's credential chain then supplies
        # them, which is how an AWS instance role is used instead.
        fields.append("PROVIDER credential_chain")

    if settings.LAKE_S3_ENDPOINT:
        fields.append(f"ENDPOINT {_sql_literal(settings.LAKE_S3_ENDPOINT)}")
    # AWS needs the bucket's region; MinIO and RustFS ignore it, so a blank one
    # is simply omitted rather than sent as an empty string.
    if settings.LAKE_S3_REGION:
        fields.append(f"REGION {_sql_literal(settings.LAKE_S3_REGION)}")
    fields.append(f"URL_STYLE {_sql_literal(settings.LAKE_S3_URL_STYLE)}")
    fields.append(f"USE_SSL {'true' if settings.LAKE_S3_USE_SSL else 'false'}")

    try:
        connection.execute(f"CREATE OR REPLACE SECRET lake ({', '.join(fields)})")
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


def read_vector_asset(uri: str, limit: int) -> dict:
    """Read up to `limit` features from a GeoParquet file in the lake.

    Returns the features, how many there are, and whether the file held more.
    The scan asks for one row beyond the cap so a file of exactly `limit`
    features is not reported as truncated.
    """
    try:
        cursor = _shared_connection().cursor()
    except duckdb.Error as exc:
        raise LakeUnavailable(str(exc)) from exc

    try:
        geometry = _geometry_column(cursor, uri)
        # The geometry column is excluded from the star so it cannot also appear
        # as a property; every remaining column becomes one.
        cursor.execute(
            f'SELECT ST_AsGeoJSON({_quote(geometry)}) AS __geometry__, '
            f'* EXCLUDE ({_quote(geometry)}) '
            f"FROM read_parquet(?) LIMIT {int(limit) + 1}",
            [uri],
        )
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
    except duckdb.Error as exc:
        raise _classify(exc, uri) from exc
    finally:
        cursor.close()

    truncated = len(rows) > limit
    features = [_feature(columns, row) for row in rows[:limit]]
    return {"count": len(features), "truncated": truncated, "features": features}


def _feature(columns: list[str], row: tuple) -> dict:
    """One GeoJSON Feature from a result row."""
    values = dict(zip(columns, row, strict=True))
    geometry = values.pop("__geometry__", None)
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
