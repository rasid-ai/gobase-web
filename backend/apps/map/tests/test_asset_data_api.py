"""GET /api/map/assets/{id}/data — the endpoint around the lake reader.

The catalog is faked at its own boundary because tests have no real `kb`
(context/integrations/kb.md). The lake is not faked: the endpoint reads a real
GeoParquet file, so the response shape is checked against actual output.
"""

import uuid

import pytest

from apps.catalog import kb
from apps.map import lake

from .conftest import write_geoparquet, write_spread_points

ASSET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def url(asset_id=ASSET_ID) -> str:
    return f"/api/map/assets/{asset_id}/data"


def ids(body) -> list[int]:
    """The `osm_id` of every feature in a response, in the order it came."""
    return [feature["properties"]["osm_id"] for feature in body["features"]]


def test_requires_authentication(api):
    assert api.get(url()).status_code == 401


def test_returns_features_for_a_vector_asset(as_viewer, monkeypatch, tmp_path):
    path = write_geoparquet(tmp_path / "asset.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    response = as_viewer.get(url())

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == str(ASSET_ID)
    assert body["count"] == 3
    assert body["next_cursor"] is None
    assert len(body["features"]) == 3
    assert body["features"][0]["type"] == "Feature"
    assert body["features"][0]["geometry"]["type"] in {"Point", "LineString", "Polygon"}


def test_the_paging_key_is_not_a_property(as_viewer, monkeypatch, tmp_path):
    """`file_row_number` is bookkeeping and must not look like a column."""
    path = write_geoparquet(tmp_path / "asset.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    properties = as_viewer.get(url()).json()["features"][0]["properties"]

    assert set(properties) == {"osm_id", "name"}


# --- paging ---------------------------------------------------------------


def test_a_full_page_offers_a_cursor(as_viewer, monkeypatch, tmp_path):
    path = write_spread_points(tmp_path / "many.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url(), {"limit": 5}).json()

    assert body["count"] == 5
    assert ids(body) == [0, 1, 2, 3, 4]
    assert body["next_cursor"] is not None


def test_the_last_page_offers_no_cursor(as_viewer, monkeypatch, tmp_path):
    """A page that does not fill the limit is the end, and says so."""
    path = write_spread_points(tmp_path / "few.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url(), {"limit": 5}).json()

    assert body["count"] == 3
    assert body["next_cursor"] is None


def test_a_page_that_exactly_fills_the_limit_is_not_reported_as_having_more(
    as_viewer, monkeypatch, tmp_path
):
    """The `limit + 1` probe exists for this case."""
    path = write_spread_points(tmp_path / "exact.parquet", rows=5)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url(), {"limit": 5}).json()

    assert body["count"] == 5
    assert body["next_cursor"] is None


def test_walking_the_cursor_covers_every_feature_once(as_viewer, monkeypatch, tmp_path):
    """No repeats and no gaps — the reason paging is keyset, not offset."""
    path = write_spread_points(tmp_path / "many.parquet", rows=23)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    seen: list[int] = []
    params = {"limit": 5}
    for _ in range(10):  # a bound, so a broken cursor fails rather than hangs
        body = as_viewer.get(url(), params).json()
        seen.extend(ids(body))
        if body["next_cursor"] is None:
            break
        params = {"limit": 5, "cursor": body["next_cursor"]}
    else:
        pytest.fail("the cursor never reached the end")

    assert seen == list(range(23))


# --- area -----------------------------------------------------------------


def test_a_bbox_returns_only_what_overlaps_it(as_viewer, monkeypatch, tmp_path):
    path = write_spread_points(tmp_path / "spread.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url(), {"bbox": "2,-0.5,5,0.5"}).json()

    assert ids(body) == [2, 3, 4, 5]
    assert body["count"] == 4
    assert body["next_cursor"] is None


def test_no_bbox_reads_the_whole_file(as_viewer, monkeypatch, tmp_path):
    path = write_spread_points(tmp_path / "spread.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    assert as_viewer.get(url()).json()["count"] == 30


def test_a_bbox_matching_nothing_is_an_empty_answer_not_an_error(as_viewer, monkeypatch, tmp_path):
    path = write_spread_points(tmp_path / "spread.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    response = as_viewer.get(url(), {"bbox": "100,40,101,41"})

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": str(ASSET_ID),
        "count": 0,
        "next_cursor": None,
        "features": [],
    }


def test_the_cursor_pages_within_the_bbox(as_viewer, monkeypatch, tmp_path):
    """Area and paging compose: the second page stays inside the same area."""
    path = write_spread_points(tmp_path / "spread.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    area = "2,-0.5,9,0.5"

    first = as_viewer.get(url(), {"bbox": area, "limit": 3}).json()
    second = as_viewer.get(url(), {"bbox": area, "limit": 3, "cursor": first["next_cursor"]}).json()

    assert ids(first) == [2, 3, 4]
    assert ids(second) == [5, 6, 7]


# --- drawn area -------------------------------------------------------------


def test_an_area_returns_only_what_is_inside_it(as_viewer, monkeypatch, tmp_path):
    """Points 6..10 sit inside the triangle's envelope and outside the triangle."""
    path = write_spread_points(tmp_path / "spread.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url(), {"area": "POLYGON((0 -1, 10 -1, 0 1, 0 -1))"}).json()

    assert ids(body) == [0, 1, 2, 3, 4, 5]


def test_a_bbox_and_an_area_together_are_refused(as_viewer, monkeypatch, tmp_path):
    """Two answers to "where" is a caller bug, not something to guess between."""
    path = write_spread_points(tmp_path / "spread.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    response = as_viewer.get(
        url(), {"bbox": "0,-1,10,1", "area": "POLYGON((0 -1, 10 -1, 0 1, 0 -1))"}
    )

    assert response.status_code == 400


def test_a_self_crossing_area_is_refused(as_viewer, monkeypatch, tmp_path):
    """DuckDB would answer this one silently and wrongly."""
    path = write_spread_points(tmp_path / "spread.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    response = as_viewer.get(url(), {"area": "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"})

    assert response.status_code == 400


# --- limits and bad input -------------------------------------------------


def test_limit_is_capped_at_the_configured_page_size(as_viewer, monkeypatch, tmp_path, settings):
    """A caller cannot talk the server into a bigger page than it allows."""
    path = write_spread_points(tmp_path / "many.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    settings.LAKE_PAGE_SIZE = 4

    body = as_viewer.get(url(), {"limit": 1000}).json()

    assert body["count"] == 4
    assert body["next_cursor"] is not None


def test_the_page_size_setting_is_the_default(as_viewer, monkeypatch, tmp_path, settings):
    path = write_spread_points(tmp_path / "many.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    settings.LAKE_PAGE_SIZE = 6

    assert as_viewer.get(url()).json()["count"] == 6


@pytest.mark.parametrize(
    "params",
    [
        {"bbox": "1,2,3"},
        {"bbox": "not,a,bounding,box"},
        {"bbox": "10,0,0,10"},
        {"bbox": "200,0,201,1"},
        {"cursor": "-1"},
        {"cursor": "abc"},
        {"limit": "0"},
    ],
    ids=[
        "short bbox",
        "unreadable bbox",
        "inside-out bbox",
        "out of range bbox",
        "negative cursor",
        "unreadable cursor",
        "zero limit",
    ],
)
def test_unreadable_parameters_are_400(as_viewer, monkeypatch, tmp_path, params):
    path = write_spread_points(tmp_path / "spread.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    assert as_viewer.get(url(), params).status_code == 400


# --- the catalog and the lake ---------------------------------------------


@pytest.mark.parametrize(
    "reason",
    ["no such id", "superseded or failed", "another modality"],
    ids=["unknown", "inactive", "raster"],
)
def test_anything_the_catalog_does_not_return_is_404(as_viewer, monkeypatch, reason):
    """All three misses are one answer: the portal does not tell them apart."""
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: None)

    assert as_viewer.get(url()).status_code == 404


def test_an_unreachable_lake_is_503(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: "s3://b/x.parquet")

    def unavailable(uri, **kwargs):
        raise lake.LakeUnavailable("connection refused")

    monkeypatch.setattr(lake, "read_vector_features", unavailable)

    assert as_viewer.get(url()).status_code == 503


def test_an_unreadable_file_is_502(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: "s3://b/x.parquet")

    def unreadable(uri, **kwargs):
        raise lake.LakeReadError("not a parquet file")

    monkeypatch.setattr(lake, "read_vector_features", unreadable)

    assert as_viewer.get(url()).status_code == 502


def test_the_lake_path_never_reaches_the_client(as_viewer, monkeypatch, tmp_path):
    """`source_uri` is a location in the bucket and stays on the server."""
    path = write_geoparquet(tmp_path / "secret-bucket-path.parquet", rows=1)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url()).content.decode()

    assert "secret-bucket-path" not in body


def test_a_malformed_uuid_is_404_not_500(as_viewer):
    assert as_viewer.get("/api/map/assets/not-a-uuid/data").status_code == 404
