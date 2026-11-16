"""GET /api/map/assets/{id}/summary — a count and a sample, for answers.

The catalog is faked at its own boundary, as for `/data`; the lake is not: the
endpoint reads a real GeoParquet file. What the reader itself does with each
operator and each refusal is in `test_lake_summary.py`; here it is the
endpoint around it (docs/adr/028).
"""

import uuid

import duckdb
import pytest

from apps.catalog import kb
from apps.map import lake

from .conftest import write_spread_points

ASSET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def url(asset_id=ASSET_ID) -> str:
    return f"/api/map/assets/{asset_id}/summary"


@pytest.fixture
def points(monkeypatch, tmp_path):
    """Thirty points one degree apart on the equator; `osm_id` is the longitude."""
    path = write_spread_points(tmp_path / "secret-bucket-path.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    return path


@pytest.fixture
def diagonal(monkeypatch, tmp_path):
    """One line across a ten-degree square: its box is the square, its shape is not."""
    path = str(tmp_path / "diagonal.parquet")
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")
    connection.execute(
        "COPY (SELECT 1 AS id, ST_GeomFromText('LINESTRING(0 0, 10 10)') AS geometry) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    return path


def test_requires_authentication(api):
    assert api.get(url()).status_code == 401


def test_counts_the_whole_file_and_samples_five_rows(as_viewer, points):
    response = as_viewer.get(url())

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": str(ASSET_ID),
        "total": 30,
        "sample": [{"osm_id": n, "name": f"feature-{n}"} for n in range(5)],
    }


def test_the_sample_size_can_be_asked_for(as_viewer, points):
    assert len(as_viewer.get(url(), {"sample": 10}).json()["sample"]) == 10
    assert as_viewer.get(url(), {"sample": 0}).json() == {
        "asset_id": str(ASSET_ID),
        "total": 30,
        "sample": [],
    }


def test_a_bbox_counts_only_what_is_inside(as_viewer, points):
    body = as_viewer.get(url(), {"bbox": "2,-0.5,5,0.5"}).json()

    assert body["total"] == 4
    assert [row["osm_id"] for row in body["sample"]] == [2, 3, 4, 5]


def test_a_bbox_is_exact_where_data_is_not(as_viewer, diagonal):
    """`/data` matches boxes, which is right for drawing; a count cannot."""
    corner = {"bbox": "6,0,10,4"}

    assert as_viewer.get(f"/api/map/assets/{ASSET_ID}/data", corner).json()["count"] == 1
    assert as_viewer.get(url(), corner).json()["total"] == 0


def test_an_area_counts_only_what_is_inside(as_viewer, points):
    body = as_viewer.get(url(), {"area": "POLYGON((1.5 -1, 4.5 -1, 4.5 1, 1.5 1, 1.5 -1))"}).json()

    assert body["total"] == 3


def test_a_filter_narrows_the_count_and_the_sample(as_viewer, points):
    body = as_viewer.get(
        url(), {"filter_column": "osm_id", "filter_op": ">", "filter_value": "26"}
    ).json()

    assert body["total"] == 3
    assert [row["osm_id"] for row in body["sample"]] == [27, 28, 29]


def test_in_takes_the_value_repeated(as_viewer, points):
    body = as_viewer.get(
        url(),
        {"filter_column": "name", "filter_op": "in", "filter_value": ["FEATURE-3", "feature-7"]},
    ).json()

    assert [row["osm_id"] for row in body["sample"]] == [3, 7]


def test_a_filter_and_a_place_together(as_viewer, points):
    body = as_viewer.get(
        url(),
        {
            "bbox": "0,-0.5,20,0.5",
            "filter_column": "name",
            "filter_op": "contains",
            "filter_value": "-1",
        },
    ).json()

    # feature-1 and feature-10 to feature-19, inside the window.
    assert body["total"] == 11


def test_data_with_the_same_area_and_filter_returns_what_was_counted(as_viewer, points):
    """With an `area`, the map draws exactly the features an answer counted."""
    asked = {
        "area": "POLYGON((0 -0.5, 20 -0.5, 20 0.5, 0 0.5, 0 -0.5))",
        "filter_column": "name",
        "filter_op": "contains",
        "filter_value": "-1",
    }

    counted = as_viewer.get(url(), {**asked, "sample": 10}).json()
    drawn = as_viewer.get(f"/api/map/assets/{ASSET_ID}/data", asked).json()

    assert drawn["count"] == counted["total"] == 11
    assert [f["properties"] for f in drawn["features"]][:10] == counted["sample"]


@pytest.fixture
def lines(monkeypatch, tmp_path):
    """Forty diagonal lines, each across its own one-degree square, with a covering column.

    Line `i` runs from (i, 0) up to (i + 1, 1), so a low, wide window crosses
    the box of every line above it and the shape of only some.
    """
    path = str(tmp_path / "lines.parquet")
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")
    connection.execute(
        "COPY (SELECT i AS id, CASE WHEN i % 2 = 0 THEN 'road' ELSE 'track' END AS kind, "
        "ST_GeomFromText('LINESTRING(' || i || ' 0, ' || (i + 1) || ' 1)') AS geometry, "
        "{'xmin': i * 1.0, 'ymin': 0.0, 'xmax': i + 1.0, 'ymax': 1.0} AS bbox "
        f"FROM range(0, 40) t(i)) TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    return path


# Along the top of the squares, from the middle of square 10 to the middle of
# square 20. Line 10 has left the window's height before it reaches its width;
# its box has not.
STRIP = (10.0, 0.9, 20.0, 1.0)
STRIP_AREA = "POLYGON((10 0.9, 20 0.9, 20 1, 10 1, 10 0.9))"
ROADS = {"filter_column": "kind", "filter_op": "equals", "filter_value": "road"}


def test_a_bbox_page_may_hold_more_than_was_counted_and_an_area_page_does_not(as_viewer, lines):
    """The documented difference (docs/adr/028): `/data` tests a bbox by boxes.

    So a client that must draw what was counted sends the rectangle as an
    `area`, which both endpoints test against the real shapes.
    """
    bbox = ",".join(str(n) for n in STRIP)

    counted = as_viewer.get(url(), {"bbox": bbox, **ROADS}).json()["total"]
    by_boxes = as_viewer.get(f"/api/map/assets/{ASSET_ID}/data", {"bbox": bbox, **ROADS}).json()
    counted_area = as_viewer.get(url(), {"area": STRIP_AREA, **ROADS}).json()["total"]
    by_area = as_viewer.get(f"/api/map/assets/{ASSET_ID}/data", {"area": STRIP_AREA, **ROADS})

    assert counted == counted_area == by_area.json()["count"]
    assert by_boxes["count"] > counted


# --- bad input ---------------------------------------------------------------


def test_an_unknown_column_is_a_400_that_lists_the_real_ones(as_viewer, points):
    response = as_viewer.get(
        url(), {"filter_column": "amenity", "filter_op": "equals", "filter_value": "school"}
    )

    assert response.status_code == 400
    assert response.json() == {
        "filter_column": ["This asset has no column `amenity`. Its columns: osm_id, name."]
    }


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"filter_column": "name", "filter_op": "<", "filter_value": "m"}, "filter_op"),
        ({"filter_column": "osm_id", "filter_op": "contains", "filter_value": "1"}, "filter_op"),
        ({"filter_column": "osm_id", "filter_op": "equals", "filter_value": "one"}, "filter_value"),
        ({"filter_column": "name", "filter_op": "like", "filter_value": "f%"}, "filter_op"),
        (
            {"filter_column": "name", "filter_op": "equals", "filter_value": ["a", "b"]},
            "filter_value",
        ),
        (
            {"filter_column": "name", "filter_op": "equals", "filter_value": "x" * 201},
            "filter_value",
        ),
        (
            {
                "filter_column": "osm_id",
                "filter_op": "in",
                "filter_value": [str(n) for n in range(21)],
            },
            "filter_value",
        ),
    ],
    ids=[
        "less than on text",
        "contains on a number",
        "text for a number",
        "unknown operator",
        "two values for equals",
        "a value too long",
        "too many values",
    ],
)
def test_a_filter_the_asset_cannot_take_is_a_400_naming_the_parameter(
    as_viewer, points, params, field
):
    response = as_viewer.get(url(), params)

    assert response.status_code == 400
    assert field in response.json()


@pytest.mark.parametrize(
    "params",
    [
        {"filter_column": "name"},
        {"filter_op": "equals"},
        {"filter_value": "x"},
        {"filter_column": "name", "filter_op": "equals"},
        {"filter_column": "name", "filter_value": "x"},
        {"filter_op": "equals", "filter_value": "x"},
    ],
)
def test_part_of_a_filter_is_refused(as_viewer, points, params):
    response = as_viewer.get(url(), params)

    assert response.status_code == 400
    assert response.json() == {
        "non_field_errors": ["A filter needs filter_column, filter_op and filter_value together."]
    }


@pytest.mark.parametrize(
    "params",
    [
        {"bbox": "1,2,3"},
        {"bbox": "10,0,0,10"},
        {"area": "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"},
        {"bbox": "0,0,1,1", "area": "POLYGON((0 0, 1 0, 1 1, 0 0))"},
        {"sample": "11"},
        {"sample": "-1"},
        {"sample": "some"},
    ],
    ids=[
        "short bbox",
        "inside-out bbox",
        "self-crossing area",
        "bbox and area",
        "sample too large",
        "negative sample",
        "unreadable sample",
    ],
)
def test_unreadable_parameters_are_400(as_viewer, points, params):
    assert as_viewer.get(url(), params).status_code == 400


def test_sql_in_the_filter_reaches_nothing(as_viewer, points):
    column = as_viewer.get(
        url(),
        {"filter_column": 'name" OR 1=1 --', "filter_op": "equals", "filter_value": "x"},
    )
    value = as_viewer.get(
        url(),
        {"filter_column": "name", "filter_op": "equals", "filter_value": "x' OR '1'='1"},
    )

    assert column.status_code == 400
    assert (value.status_code, value.json()["total"]) == (200, 0)


# --- the catalog and the lake ------------------------------------------------


def test_anything_the_catalog_does_not_return_is_404(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: None)

    assert as_viewer.get(url()).status_code == 404


def test_a_malformed_uuid_is_404_not_500(as_viewer):
    assert as_viewer.get("/api/map/assets/not-a-uuid/summary").status_code == 404


def test_an_unreachable_lake_is_503(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: "s3://b/x.parquet")

    def unavailable(uri, **kwargs):
        raise lake.LakeUnavailable("connection refused")

    monkeypatch.setattr(lake, "summarize_vector_features", unavailable)

    assert as_viewer.get(url()).status_code == 503


def test_an_unreadable_file_is_502(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: "s3://b/x.parquet")

    def unreadable(uri, **kwargs):
        raise lake.LakeReadError("not a parquet file")

    monkeypatch.setattr(lake, "summarize_vector_features", unreadable)

    assert as_viewer.get(url()).status_code == 502


def test_the_lake_path_never_reaches_the_client(as_viewer, points):
    refused = as_viewer.get(
        url(), {"filter_column": "nope", "filter_op": "equals", "filter_value": "x"}
    )

    assert "secret-bucket-path" not in as_viewer.get(url()).content.decode()
    assert "secret-bucket-path" not in refused.content.decode()


def test_an_api_key_may_read_it(api, db, points):
    """The Ask agent calls with an API key, which may only read (docs/adr/021)."""
    from django.contrib.auth.models import User

    from apps.accounts.models import ApiKey, Role, UserProfile

    user = User.objects.create_user(username="gobase-agent")
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    _, key = ApiKey.issue(user, "test")
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")

    assert api.get(url()).status_code == 200
