"""The lake reader, run against real GeoParquet files.

These do not mock DuckDB. A local path exercises the same code an s3:// URI
does — only the endpoint configuration differs — so the parsing, the geometry
column discovery and the truncation arithmetic are all covered for real.
"""

import pytest

from apps.map import lake

from .conftest import write_geoparquet


def test_reads_features_with_properties(tmp_path):
    path = write_geoparquet(tmp_path / "mixed.parquet", rows=3)

    result = lake.read_vector_asset(path, limit=100)

    assert result["count"] == 3
    assert result["truncated"] is False

    kinds = {feature["geometry"]["type"] for feature in result["features"]}
    assert kinds == {"Point", "LineString", "Polygon"}

    first = result["features"][0]
    assert first["type"] == "Feature"
    assert first["properties"]["name"] == "feature-0"
    # The geometry column must not survive as a property as well.
    assert "geometry" not in first["properties"]


def test_truncates_at_the_cap_and_says_so(tmp_path):
    path = write_geoparquet(tmp_path / "big.parquet", rows=25)

    result = lake.read_vector_asset(path, limit=10)

    assert result["count"] == 10
    assert result["truncated"] is True


def test_a_file_of_exactly_the_cap_is_not_truncated(tmp_path):
    """The scan reads limit+1 rows precisely so this case is not a false positive."""
    path = write_geoparquet(tmp_path / "exact.parquet", rows=10)

    result = lake.read_vector_asset(path, limit=10)

    assert result["count"] == 10
    assert result["truncated"] is False


def test_missing_file_is_a_read_error(tmp_path):
    with pytest.raises(lake.LakeReadError):
        lake.read_vector_asset(str(tmp_path / "absent.parquet"), limit=10)


def test_a_file_that_is_not_parquet_is_a_read_error(tmp_path):
    path = tmp_path / "not-parquet.parquet"
    path.write_text("this is not a parquet file")

    with pytest.raises(lake.LakeReadError):
        lake.read_vector_asset(str(path), limit=10)


def test_an_unreachable_endpoint_is_unavailable_not_a_read_error(settings):
    """A dead endpoint must be 503, not 502: the file is not the problem."""
    settings.LAKE_S3_ENDPOINT = "127.0.0.1:1"
    settings.LAKE_S3_USE_SSL = False
    settings.LAKE_S3_URL_STYLE = "path"
    settings.LAKE_S3_ACCESS_KEY = "unused"
    settings.LAKE_S3_SECRET_KEY = "unused"
    lake.reset()

    with pytest.raises(lake.LakeUnavailable):
        lake.read_vector_asset("s3://nothing/here.parquet", limit=10)


def test_values_that_json_cannot_hold_become_strings(tmp_path):
    """Properties are whatever columns the file has, so types are not known."""
    import duckdb

    path = str(tmp_path / "typed.parquet")
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")
    connection.execute(
        f"COPY (SELECT TIMESTAMP '2026-09-11 08:00:00' AS seen, "
        f"DECIMAL '1.25' AS ratio, ST_Point(1, 2) AS geometry) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()

    result = lake.read_vector_asset(path, limit=10)

    properties = result["features"][0]["properties"]
    assert properties["seen"] == "2026-09-11 08:00:00"
    assert float(properties["ratio"]) == 1.25


def test_lake_configuration_is_visible_from_a_cursor(settings):
    """Regression: every request runs on `connection.cursor()`.

    `SET s3_*` is session-scoped and a cursor opens its own session, so the
    legacy settings vanish and requests go out signed with an empty region. The
    store answers 404, which is indistinguishable from a missing file. A secret
    lives in the database instead, so a cursor sees it.
    """
    settings.LAKE_S3_ENDPOINT = "store.invalid:9000"
    settings.LAKE_S3_REGION = "eu-central-1"
    settings.LAKE_S3_URL_STYLE = "path"
    settings.LAKE_S3_USE_SSL = False
    settings.LAKE_S3_ACCESS_KEY = "key"
    settings.LAKE_S3_SECRET_KEY = "secret"
    lake.reset()

    cursor = lake._shared_connection().cursor()
    try:
        secrets = cursor.execute("SELECT name FROM duckdb_secrets()").fetchall()
    finally:
        cursor.close()

    assert ("lake",) in secrets


def test_blank_credentials_use_the_credential_chain(settings):
    """An AWS instance role supplies keys instead of .env holding them."""
    settings.LAKE_S3_ACCESS_KEY = ""
    settings.LAKE_S3_SECRET_KEY = ""
    lake.reset()

    cursor = lake._shared_connection().cursor()
    try:
        provider = cursor.execute(
            "SELECT provider FROM duckdb_secrets() WHERE name = 'lake'"
        ).fetchone()
    finally:
        cursor.close()

    assert provider[0] == "credential_chain"
