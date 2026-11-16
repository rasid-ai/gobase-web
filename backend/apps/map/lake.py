"""The only module that reads the lake.

Everything above this speaks GeoJSON — or, for a document's PDF, bytes. The
lake is S3-compatible object storage holding GeoParquet written by the data
platform; the catalog gives the URI and this module turns the file behind it
into features (docs/adr/008). It also holds the PDFs the documents were parsed
from, which `read_blob` hands over whole (docs/adr/027).

DuckDB rather than a Python GeoParquet reader: it pushes the area filter and
the row cap down into the scan, so a file is never fully materialised to return
the part of it the map can see — and it writes the page's GeoJSON itself, so no
feature ever becomes a Python object on its way out (docs/adr/015).

DuckDB reads the lake; it never touches Postgres. `kb` stays on Django's
connection and its read-only role (docs/adr/002).
"""

import json
import logging
import math
import re
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import duckdb
from django.conf import settings

logger = logging.getLogger(__name__)


class LakeUnavailable(Exception):
    """The lake could not be reached: refused, unresolved, or not authorised."""


class LakeReadError(Exception):
    """The lake answered, but the file is missing or not readable as GeoParquet."""


# The attribute filter's fixed operators, and its caps (docs/adr/028).
FILTER_OPERATORS = ("equals", "contains", "in", "<", ">")
MAX_FILTER_VALUES = 20
MAX_FILTER_VALUE_CHARS = 200
# How many column names a refusal lists, so the caller's next try can be right.
_LISTED_COLUMNS = 100


@dataclass(frozen=True)
class AttributeFilter:
    """One column, one operator, and the value or values to compare with.

    Not SQL. The column is checked against the file's own columns and quoted;
    every value is a bound parameter (docs/adr/028). Values arrive as text
    and are cast to the column's type.
    """

    column: str
    op: str
    values: tuple[str, ...]


class FilterRefused(ValueError):
    """The filter cannot be applied to this file. The caller's mistake: a 400.

    `field` is the request parameter at fault, so the answer can say which.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


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


def _describe(cursor, uri: str) -> list[tuple[str, str]]:
    """Every column in the file, with its DuckDB type, in file order."""
    cursor.execute("DESCRIBE SELECT * FROM read_parquet(?)", [uri])
    return [(name, str(dtype)) for name, dtype, *_ in cursor.fetchall()]


def _covering_bbox_column(columns: list[tuple[str, str]], uri: str) -> str | None:
    """The GeoParquet 1.1 covering column, or None if the file has none.

    One box per feature, derived from the geometry. It exists for readers to
    prune with, so it is a filter and never a property.

    Detected by name and type rather than from the `geo` metadata's `covering`
    key, because the same rule has to match a file DuckDB wrote — `COPY` emits
    the column but not that metadata. `gobase/cli/export.py:is_covering_bbox`
    is the other half of this agreement and tests exactly the same thing; the
    two must not drift.
    """
    for name, dtype in columns:
        if name == COVERING_BBOX and dtype.upper().startswith("STRUCT(XMIN"):
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


@dataclass(frozen=True)
class _Scope:
    """What a read is narrowed to: the file's columns, and the WHERE that keeps the rows."""

    geometry: str
    covering: str | None
    columns: list[tuple[str, str]]
    conditions: tuple[str, ...]
    params: tuple


def _scope(
    reader,
    uri: str,
    *,
    bbox: tuple[float, float, float, float] | None,
    area: str | None,
    attribute_filter: AttributeFilter | None,
    exact: bool = False,
) -> _Scope:
    """The conditions that keep a read to a place and to an attribute filter.

    Shared by the page read and the summary, so an `area` and a filter mean
    the same rows to both. Each condition binds its own parameters, in order;
    the caller puts the file's URI before them.

    `exact` decides how a `bbox` without an `area` is tested. A page for a
    window tests boxes against the box, which is cheap and slightly
    over-inclusive. A count has to be exact, so it tests the real geometry
    against the box.
    """
    if area is not None and bbox is None:
        raise ValueError("an area needs its envelope passed as bbox, for pruning")

    geometry_name = _geometry_column(reader, uri)
    columns = _describe(reader, uri)
    covering = _covering_bbox_column(columns, uri)
    geometry = _quote(geometry_name)

    conditions: list[str] = []
    params: list = []
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

        if area is not None:
            # A drawn polygon is tested exactly. Its outline is on screen,
            # so a feature drawn outside it reads as a bug rather than as
            # an optimisation: over Beirut the loose box test returns 15%
            # more buildings than lie inside the polygon. The exact test
            # only runs on what the envelope let through, which is why it
            # is affordable (56 ms against 371 ms unpruned, docs/adr/014).
            conditions.append(f"ST_Intersects({geometry}, ST_GeomFromText(?))")
            params.append(area)
        elif exact:
            # A count is a figure in an answer, so a feature whose box
            # overlaps the window but whose shape does not must not be in
            # it (docs/adr/028). The covering column still prunes first.
            conditions.append(f"ST_Intersects({geometry}, ST_MakeEnvelope(?, ?, ?, ?))")
            params.extend(bbox)
        else:
            # A window is tested on bounding boxes, not real geometry:
            # `ST_Intersects_Extent` is a box-against-box test and the
            # exact predicate does real geometry work on every surviving
            # row, measured 18-40% slower for the same rows.
            #
            # It is over-inclusive and never under-inclusive: a feature
            # whose box overlaps the window but whose geometry does not
            # comes back too. For a window that is free — it lands off
            # screen and MapLibre clips it. Anything counting or answering
            # from this must know it (docs/adr/012).
            conditions.append(f"ST_Intersects_Extent({geometry}, ST_MakeEnvelope(?, ?, ?, ?))")
            params.extend(bbox)

    if attribute_filter is not None:
        attributes = [
            (name, dtype)
            for name, dtype in columns
            if name not in (geometry_name, covering, "file_row_number")
        ]
        condition, values = _filter_condition(reader, attributes, attribute_filter)
        conditions.append(condition)
        params.extend(values)

    return _Scope(geometry_name, covering, columns, tuple(conditions), tuple(params))


# How a column's DuckDB type may be filtered. The type text comes from
# DESCRIBE, and only a type matching one of these is ever written into a CAST.
_TEXT_TYPES = re.compile(r"VARCHAR|UUID|ENUM\(.*\)")
_NUMBER_TYPES = re.compile(
    r"U?(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT)|FLOAT|DOUBLE|REAL|DECIMAL\(\d+,\s*\d+\)"
)
_TIME_TYPES = re.compile(r"DATE|TIMESTAMP(_S|_MS|_NS)?|TIMESTAMP WITH TIME ZONE|TIME")


def _filter_condition(
    reader, attributes: list[tuple[str, str]], asked: AttributeFilter
) -> tuple[str, list]:
    """The SQL for one attribute filter and the values it binds, or `FilterRefused`.

    The semantics (docs/adr/028):

    - `equals` and `in` compare text without regard to case, and any other
      type after casting the value to the column's type.
    - `contains` is for text only, without regard to case. `%` and `_` in the
      value are ordinary characters.
    - `<` and `>` are for numbers, dates and timestamps only.
    - A null never matches, and neither does NaN for `<` or `>`.

    Nothing the caller sent is written into the SQL: the column name is the
    file's own, found by comparing, and each value is a parameter.
    """
    if asked.op not in FILTER_OPERATORS:
        raise FilterRefused(
            "filter_op", f"filter_op must be one of: {', '.join(FILTER_OPERATORS)}."
        )
    values = list(asked.values)
    if not values:
        raise FilterRefused("filter_value", "A filter needs a value.")
    if asked.op != "in" and len(values) != 1:
        raise FilterRefused("filter_value", f"`{asked.op}` takes one value; use `in` for several.")
    if len(values) > MAX_FILTER_VALUES:
        raise FilterRefused("filter_value", f"`in` takes at most {MAX_FILTER_VALUES} values.")
    if any(len(value) > MAX_FILTER_VALUE_CHARS for value in values):
        raise FilterRefused(
            "filter_value", f"A filter value is at most {MAX_FILTER_VALUE_CHARS} characters."
        )

    dtype = next((dtype for name, dtype in attributes if name == asked.column), None)
    if dtype is None:
        names = [name for name, _ in attributes]
        listed = ", ".join(names[:_LISTED_COLUMNS]) or "none"
        more = f", and {len(names) - _LISTED_COLUMNS} more" if len(names) > _LISTED_COLUMNS else ""
        raise FilterRefused(
            "filter_column",
            f"This asset has no column `{asked.column}`. Its columns: {listed}{more}.",
        )
    column = _quote(asked.column)
    kind = dtype.upper()

    if _TEXT_TYPES.fullmatch(kind):
        if asked.op in ("<", ">"):
            raise FilterRefused(
                "filter_op",
                f"`{asked.op}` needs a number or a date; `{asked.column}` is text ({dtype}).",
            )
        if asked.op == "contains":
            if not values[0]:
                raise FilterRefused("filter_value", "`contains` needs some text to look for.")
            # `contains` is a plain substring test: no wildcard means anything.
            return f"contains(lower({column}::VARCHAR), lower(?))", values
        marks = ", ".join("lower(?)" for _ in values)
        return f"lower({column}::VARCHAR) IN ({marks})", values

    number = bool(_NUMBER_TYPES.fullmatch(kind))
    if not (number or _TIME_TYPES.fullmatch(kind) or kind == "BOOLEAN"):
        raise FilterRefused(
            "filter_column", f"Column `{asked.column}` ({dtype}) cannot be filtered on."
        )
    if asked.op == "contains":
        raise FilterRefused(
            "filter_op", f"`contains` is for text columns; `{asked.column}` is {dtype}."
        )
    if kind == "BOOLEAN" and asked.op in ("<", ">"):
        raise FilterRefused(
            "filter_op", f"`{asked.op}` needs a number or a date; `{asked.column}` is {dtype}."
        )
    if _WHOLE_TYPES.fullmatch(kind) and asked.op in ("equals", "in"):
        # A whole-number column equals only whole numbers that fit its type,
        # so each value is compared in that type and a 64-bit id stays exact.
        # `1.5`, or a number too large for the column, is a number no row
        # equals: it is left out, not compared as a DOUBLE, which would round
        # the column's large values together (docs/adr/028).
        kept = []
        for value in values:
            whole = _whole_number(value)
            if whole is _NOT_A_NUMBER:
                raise FilterRefused(
                    "filter_value",
                    f"`{value}` is not a value column `{asked.column}` ({dtype}) can hold.",
                )
            if whole is not None and _casts(reader, whole, kind):
                kept.append(whole)
        if not kept:
            return "FALSE", []
        marks = ", ".join(f"CAST(? AS {kind})" for _ in kept)
        return f"{column} IN ({marks})", kept

    casts = []
    for value in values:
        cast = _cast_type(reader, value, kind, number)
        if cast is None:
            raise FilterRefused(
                "filter_value",
                f"`{value}` is not a value column `{asked.column}` ({dtype}) can hold.",
            )
        casts.append(cast)

    if asked.op in ("<", ">"):
        condition = f"{column} {asked.op} CAST(? AS {casts[0]})"
        if kind in _FLOATING:
            # DuckDB orders NaN above every number; it is not "greater than 5".
            condition += f" AND NOT isnan({column})"
        return condition, values
    # One comparison per value, not one IN list: a list has one type, so a
    # single value cast to DOUBLE would turn every comparison into a DOUBLE one.
    tests = " OR ".join(f"{column} = CAST(? AS {cast})" for cast in casts)
    return f"({tests})", values


_WHOLE_NUMBER = re.compile(r"[+-]?[0-9]+")
_WHOLE_TYPES = re.compile(r"U?(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT)")
_SINGLE_TYPES = {"FLOAT", "REAL"}
_NOT_A_NUMBER = object()
# No whole-number type holds more digits than this (UHUGEINT has 39).
_MAX_WHOLE_DIGITS = 40


def _whole_number(value: str):
    """A number sent as text, as a whole number's digits.

    None when it is a number but not a whole one a column could hold (`1.5`,
    `1e99`), and `_NOT_A_NUMBER` when it is not a finite number at all.
    `7.0` and `7e0` are 7.
    """
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return _NOT_A_NUMBER
    if not number.is_finite():
        return _NOT_A_NUMBER
    if number.adjusted() >= _MAX_WHOLE_DIGITS or number != number.to_integral_value():
        return None
    return str(int(number))


def _casts(reader, value: str, kind: str) -> bool:
    """Whether a value sent as text casts to a type. `kind` is never the caller's text."""
    reader.execute(f"SELECT TRY_CAST(? AS {kind}) IS NOT NULL", [value])
    return bool(reader.fetchone()[0])


def _cast_type(reader, value: str, kind: str, number: bool) -> str | None:
    """The type to cast a value sent as text to, or None if the column cannot hold it.

    A number is compared as a DOUBLE, so `1.5` against a whole-number column
    means 1.5 and is not rounded to 2 by a cast to the column's type. Two
    exceptions keep a comparison exact:

    - A whole number against a whole-number column is cast to that type: a
      64-bit id does not fit a DOUBLE exactly.
    - Any number against a 32-bit FLOAT column is cast to FLOAT. Widened to a
      DOUBLE, the column's 0.1 is 0.100000001490116, which equals no `0.1`.
    """
    if number:
        try:
            if not math.isfinite(float(value)):
                return None
        except ValueError:
            return None
        if kind in _SINGLE_TYPES:
            pass
        elif not (_WHOLE_TYPES.fullmatch(kind) and _WHOLE_NUMBER.fullmatch(value)):
            kind = "DOUBLE"
    if _casts(reader, value, kind):
        return kind
    if number and kind != "DOUBLE":
        # A number too large for the column's type: no row equals it, but it
        # is still a number to compare with.
        return "DOUBLE"
    return None


def summarize_vector_features(
    uri: str,
    *,
    sample: int,
    bbox: tuple[float, float, float, float] | None = None,
    area: str | None = None,
    attribute_filter: AttributeFilter | None = None,
) -> dict:
    """How many features match, exactly, and the properties of the first few.

    For answers, not for drawing (docs/adr/028). The same scope as
    `read_vector_features`, with one difference: a `bbox` on its own is
    tested against each feature's real geometry, because a count has to be
    exact. The covering column still prunes first.

    Returns `total` and `sample`: up to `sample` rows of properties in file
    order, no geometry, written by the same rules as a page's properties.
    """
    try:
        reader = _shared_connection().cursor()
    except duckdb.Error as exc:
        raise LakeUnavailable(str(exc)) from exc

    try:
        scope = _scope(
            reader, uri, bbox=bbox, area=area, attribute_filter=attribute_filter, exact=True
        )
        where = f"WHERE {' AND '.join(scope.conditions)}" if scope.conditions else ""
        params = [uri, *scope.params]

        reader.execute(f"SELECT count(*) FROM read_parquet(?) {where}", params)
        total = int(reader.fetchone()[0])

        rows = None
        if total and sample > 0:
            properties = _properties(scope.columns, exclude={scope.geometry, scope.covering})
            reader.execute(
                f"""
                SELECT string_agg(__properties__, ',' ORDER BY __cursor__)
                FROM (
                    SELECT file_row_number AS __cursor__, {properties} AS __properties__
                    FROM read_parquet(?, file_row_number = true)
                    {where}
                    ORDER BY file_row_number
                    LIMIT {int(sample)}
                )
                """,
                params,
            )
            rows = reader.fetchone()[0]
    except duckdb.Error as exc:
        raise _classify(exc, uri) from exc
    finally:
        reader.close()

    # A handful of rows, so parsing them costs nothing; the response is small
    # and goes through DRF like any other.
    return {"total": total, "sample": json.loads(f"[{rows or ''}]")}


def read_vector_features(
    uri: str,
    *,
    limit: int,
    bbox: tuple[float, float, float, float] | None = None,
    area: str | None = None,
    cursor: int | None = None,
    attribute_filter: AttributeFilter | None = None,
) -> dict:
    """Read one page of features from a GeoParquet file in the lake.

    `bbox` is `(min_lon, min_lat, max_lon, max_lat)` in SRID 4326. It keeps the
    read to the area the caller asked about; without it the whole file is in
    scope. On its own it matches on bounding boxes, so it is slightly
    over-inclusive — see the filter below.

    `area` is a drawn polygon as WKT, and refines `bbox` rather than replacing
    it: the caller passes the polygon's envelope as `bbox` and the polygon as
    `area`. The envelope does the pruning, which is what makes a polygon
    affordable, and the polygon then decides exactly. It arrives validated by
    `AreaField`, which is the only thing standing between a self-intersecting
    shape and a silently wrong answer.

    `cursor` is the `next_cursor` the previous page returned.

    `attribute_filter` keeps only the rows whose column matches
    (docs/adr/028). A filter the file cannot take raises `FilterRefused`.

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
    if area is not None and bbox is None:
        raise ValueError("an area needs its envelope passed as bbox, for pruning")

    try:
        reader = _shared_connection().cursor()
    except duckdb.Error as exc:
        raise LakeUnavailable(str(exc)) from exc

    try:
        scope = _scope(reader, uri, bbox=bbox, area=area, attribute_filter=attribute_filter)
        geometry_name, covering, columns = scope.geometry, scope.covering, scope.columns
        geometry = _quote(geometry_name)
        conditions, params = list(scope.conditions), [uri, *scope.params]
        if cursor is not None:
            conditions.append("file_row_number > ?")
            params.append(cursor)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # The page is written as JSON by DuckDB, not by Python. Today's
        # alternative parsed every geometry DuckDB had already written as JSON
        # back into Python objects, built a dict per feature, and serialised
        # the lot again: 731 ms for 10,000 buildings, against 144 ms for this
        # (docs/adr/015).
        #
        # `LIMIT limit + 1` still decides whether there is a next page; the
        # extra row is counted but kept out of the features and the cursor.
        page = int(limit)
        properties = _properties(columns, exclude={geometry_name, covering})
        reader.execute(
            f"""
            WITH page AS (
                SELECT file_row_number AS __cursor__,
                       ST_AsGeoJSON({geometry}) AS __geometry__,
                       {properties} AS __properties__
                FROM read_parquet(?, file_row_number = true)
                {where}
                ORDER BY file_row_number
                LIMIT {page + 1}
            ),
            numbered AS (
                SELECT row_number() OVER (ORDER BY __cursor__) AS __n__, * FROM page
            )
            SELECT count(*) FILTER (WHERE __n__ <= {page}),
                   count(*) > {page},
                   max(__cursor__) FILTER (WHERE __n__ <= {page}),
                   string_agg(
                       '{{"type":"Feature","geometry":' || coalesce(__geometry__, 'null')
                       || ',"properties":' || __properties__ || '}}',
                       ',' ORDER BY __cursor__
                   ) FILTER (WHERE __n__ <= {page})
            FROM numbered
            """,
            params,
        )
        count, more, last, features = reader.fetchone()
    except duckdb.Error as exc:
        raise _classify(exc, uri) from exc
    finally:
        reader.close()

    return {
        "count": count,
        "next_cursor": int(last) if more else None,
        # A JSON array as text, ready to be written into a response unparsed.
        "features_json": f"[{features or ''}]",
    }


def read_blob(uri: str) -> bytes:
    """Read one object from the lake whole, as bytes.

    For a document's PDF (docs/adr/027). The object comes back in memory in
    one piece — DuckDB's `read_blob` has no streaming form — which is right
    for the PDFs the catalog holds, hundreds of kilobytes each, and would not
    be for a multi-gigabyte object. A local path reads the same way, which is
    what the tests use.
    """
    try:
        reader = _shared_connection().cursor()
    except duckdb.Error as exc:
        raise LakeUnavailable(str(exc)) from exc

    try:
        reader.execute("SELECT content FROM read_blob(?)", [uri])
        row = reader.fetchone()
    except duckdb.Error as exc:
        raise _classify(exc, uri) from exc
    finally:
        reader.close()

    if row is None:
        raise LakeReadError(f"Nothing read from {uri}")
    return bytes(row[0])


# DuckDB's `to_json` writes a non-finite float as a bare `NaN` or `Infinity`,
# which is not JSON: one such value would make the browser reject the whole
# page. These types are the ones that can hold one.
_FLOATING = {"DOUBLE", "FLOAT", "REAL"}


def _properties(columns: list[tuple[str, str]], *, exclude: set) -> str:
    """SQL for one row's properties as a JSON object, as text.

    Every column but the geometry, the row number and the covering box —
    those are the file's structure, not its data. Written column by column
    from DESCRIBE rather than with a star, for two reasons: a file with no
    attribute columns at all has to produce `{}` (DuckDB refuses to pack an
    empty struct), and a floating-point column has to turn NaN and infinity
    into null so the output is always valid JSON.

    `to_json` does the rest: timestamps and dates as text, decimals as
    numbers, and names like `fill-opacity` escaped properly.
    """
    fields = []
    for name, dtype in columns:
        if name in exclude:
            continue
        column = _quote(name)
        value = (
            f"CASE WHEN isfinite({column}) THEN {column} END"
            if dtype.upper() in _FLOATING
            else column
        )
        fields.append(f"{column} := {value}")
    if not fields:
        return "'{}'"
    return f"to_json(struct_pack({', '.join(fields)}))::VARCHAR"


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
