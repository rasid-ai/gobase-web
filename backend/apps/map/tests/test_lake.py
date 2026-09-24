"""The lake reader, run against real GeoParquet files.

These do not mock DuckDB. A local path exercises the same code an s3:// URI
does — only the endpoint configuration differs — so the parsing, the geometry
column discovery, the area filter and the paging arithmetic are all covered
for real.
"""

import logging

import pytest

from apps.map import lake

from .conftest import write_covered_points, write_geoparquet, write_spread_points


def test_reads_features_with_properties(tmp_path):
    path = write_geoparquet(tmp_path / "mixed.parquet", rows=3)

    result = lake.read_vector_features(path, limit=100)

    assert result["count"] == 3
    assert result["next_cursor"] is None

    kinds = {feature["geometry"]["type"] for feature in result["features"]}
    assert kinds == {"Point", "LineString", "Polygon"}

    first = result["features"][0]
    assert first["type"] == "Feature"
    assert first["properties"]["name"] == "feature-0"
    # The geometry column must not survive as a property as well.
    assert "geometry" not in first["properties"]


def test_a_full_page_offers_a_cursor(tmp_path):
    path = write_geoparquet(tmp_path / "big.parquet", rows=25)

    result = lake.read_vector_features(path, limit=10)

    assert result["count"] == 10
    assert result["next_cursor"] is not None


def test_a_file_of_exactly_the_page_size_offers_no_cursor(tmp_path):
    """The scan reads limit+1 rows precisely so this case is not a false positive."""
    path = write_geoparquet(tmp_path / "exact.parquet", rows=10)

    result = lake.read_vector_features(path, limit=10)

    assert result["count"] == 10
    assert result["next_cursor"] is None


def test_a_bbox_keeps_the_read_to_that_area(tmp_path):
    """The filter is pushed into the scan, so the rest of the file is never built."""
    path = write_spread_points(tmp_path / "spread.parquet", rows=50)

    result = lake.read_vector_features(path, limit=100, bbox=(10.0, -0.5, 13.0, 0.5))

    assert result["count"] == 4
    assert [f["properties"]["osm_id"] for f in result["features"]] == [10, 11, 12, 13]


def test_paging_repeats_nothing_and_skips_nothing(tmp_path):
    """Why paging is keyset on the file's row number rather than by offset.

    `read_parquet` has no inherent order and DuckDB scans in parallel, so an
    offset would slide under the pages and lose rows between them.
    """
    path = write_spread_points(tmp_path / "many.parquet", rows=47)

    seen: list[int] = []
    cursor = None
    for _ in range(20):  # a bound, so a broken cursor fails rather than hangs
        page = lake.read_vector_features(path, limit=7, cursor=cursor)
        seen.extend(f["properties"]["osm_id"] for f in page["features"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("the cursor never reached the end")

    assert seen == list(range(47))


def test_a_covering_bbox_column_is_used_and_never_shown(tmp_path):
    """The covering column filters; it is not the file's data.

    Silver writes one box per feature so DuckDB can skip row groups without
    reading geometry. It is derived from the geometry, so it must not arrive as
    a property — the map would draw a `bbox` field nobody put in the file.
    """
    path = write_covered_points(tmp_path / "covered.parquet", rows=200)

    result = lake.read_vector_features(path, limit=100, bbox=(10.0, -0.5, 13.0, 0.5))

    assert [f["properties"]["osm_id"] for f in result["features"]] == [10, 11, 12, 13]
    assert set(result["features"][0]["properties"]) == {"osm_id", "name"}


def test_a_covered_file_and_a_plain_one_answer_the_same(tmp_path):
    """The range test prunes; it must not change the answer.

    The two files hold identical features and differ only in the covering
    column, so any difference here is the covering filter dropping real rows.
    """
    covered = write_covered_points(tmp_path / "covered.parquet", rows=200)
    plain = write_spread_points(tmp_path / "plain.parquet", rows=200)
    area = (10.0, -0.5, 13.0, 0.5)

    def ids(path):
        page = lake.read_vector_features(path, limit=100, bbox=area)
        return [f["properties"]["osm_id"] for f in page["features"]]

    assert ids(covered) == ids(plain)


def test_a_file_without_a_covering_column_still_reads(tmp_path, caplog):
    """Silver writes one for every asset, so a file without it is a defect.

    It is reported and not raised: the file reads correctly either way, it just
    reads all of itself to answer an area query. Breaking the map over it would
    be worse than the thing being reported.
    """
    path = write_spread_points(tmp_path / "plain.parquet", rows=30)

    with caplog.at_level(logging.WARNING, logger="apps.map.lake"):
        result = lake.read_vector_features(path, limit=100, bbox=(2.0, -0.5, 5.0, 0.5))

    assert result["count"] == 4
    assert "covering column" in caplog.text


def test_the_missing_covering_column_is_reported_once_per_file(tmp_path, caplog):
    """One line per file, not one per pan. A live map re-reads constantly."""
    path = write_spread_points(tmp_path / "plain.parquet", rows=30)

    with caplog.at_level(logging.WARNING, logger="apps.map.lake"):
        for _ in range(3):
            lake.read_vector_features(path, limit=100, bbox=(2.0, -0.5, 5.0, 0.5))

    assert sum("covering column" in record.message for record in caplog.records) == 1


def test_missing_file_is_a_read_error(tmp_path):
    with pytest.raises(lake.LakeReadError):
        lake.read_vector_features(str(tmp_path / "absent.parquet"), limit=10)


def test_a_file_that_is_not_parquet_is_a_read_error(tmp_path):
    path = tmp_path / "not-parquet.parquet"
    path.write_text("this is not a parquet file")

    with pytest.raises(lake.LakeReadError):
        lake.read_vector_features(str(path), limit=10)


def test_an_unreachable_endpoint_is_unavailable_not_a_read_error(settings):
    """A dead endpoint must be 503, not 502: the file is not the problem."""
    settings.LAKE_S3_ENDPOINT = "127.0.0.1:1"
    settings.LAKE_S3_USE_SSL = False
    settings.LAKE_S3_URL_STYLE = "path"
    settings.LAKE_S3_ACCESS_KEY = "unused"
    settings.LAKE_S3_SECRET_KEY = "unused"
    lake.reset()

    with pytest.raises(lake.LakeUnavailable):
        lake.read_vector_features("s3://nothing/here.parquet", limit=10)


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

    result = lake.read_vector_features(path, limit=10)

    properties = result["features"][0]["properties"]
    assert properties["seen"] == "2026-09-11 08:00:00"
    assert float(properties["ratio"]) == 1.25


def test_lake_configuration_is_visible_from_a_cursor(settings):
    """Regression: every request runs on `connection.cursor()`.

    `SET s3_*` is session-scoped and a cursor opens its own session, so the
    legacy settings vanish and the store is reached with no configuration at
    all. It answers 404, which is indistinguishable from a missing file. A
    secret lives in the database instead, so a cursor sees it.
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


class TestSecretStatement:
    """The CREATE SECRET text, checked without DuckDB.

    Deliberately not executed: `credential_chain` is implemented by DuckDB's
    `aws` extension, which is downloaded on first use. Asserting on the
    statement keeps these deterministic on a machine that has never fetched it
    — which is every CI runner.
    """

    def test_nothing_configured_means_no_secret(self, settings):
        """A local path needs no object store, and CI configures none."""
        settings.LAKE_S3_ACCESS_KEY = ""
        settings.LAKE_S3_SECRET_KEY = ""
        settings.LAKE_S3_ENDPOINT = ""
        settings.LAKE_S3_REGION = ""

        assert lake._secret_statement() is None

    def test_static_keys_are_sent_as_key_id_and_secret(self, settings):
        settings.LAKE_S3_ACCESS_KEY = "an-access-key"
        settings.LAKE_S3_SECRET_KEY = "a-secret-key"
        settings.LAKE_S3_ENDPOINT = "127.0.0.1:9000"
        settings.LAKE_S3_REGION = ""

        statement = lake._secret_statement()

        assert "KEY_ID 'an-access-key'" in statement
        assert "SECRET 'a-secret-key'" in statement
        assert "credential_chain" not in statement
        # MinIO has no regions; a blank one is omitted, never sent empty.
        assert "REGION" not in statement

    def test_configured_without_keys_uses_the_credential_chain(self, settings):
        """An AWS instance role supplies the keys instead of .env holding them."""
        settings.LAKE_S3_ACCESS_KEY = ""
        settings.LAKE_S3_SECRET_KEY = ""
        settings.LAKE_S3_ENDPOINT = ""
        settings.LAKE_S3_REGION = "eu-central-1"

        statement = lake._secret_statement()

        assert "PROVIDER credential_chain" in statement
        assert "REGION 'eu-central-1'" in statement
        assert "KEY_ID" not in statement

    def test_a_quote_in_a_value_cannot_break_out(self, settings):
        """The statement is built as text, so the values must be escaped."""
        settings.LAKE_S3_ACCESS_KEY = "ke'y"
        settings.LAKE_S3_SECRET_KEY = "sec'ret"
        settings.LAKE_S3_ENDPOINT = ""
        settings.LAKE_S3_REGION = ""

        statement = lake._secret_statement()

        assert "KEY_ID 'ke''y'" in statement
        assert "SECRET 'sec''ret'" in statement


def test_a_local_file_reads_with_no_object_store_configured(settings, tmp_path):
    """The lake reader must work for a local path without any S3 settings."""
    settings.LAKE_S3_ACCESS_KEY = ""
    settings.LAKE_S3_SECRET_KEY = ""
    settings.LAKE_S3_ENDPOINT = ""
    settings.LAKE_S3_REGION = ""
    lake.reset()

    path = write_geoparquet(tmp_path / "local.parquet", rows=2)

    assert lake.read_vector_features(path, limit=10)["count"] == 2
