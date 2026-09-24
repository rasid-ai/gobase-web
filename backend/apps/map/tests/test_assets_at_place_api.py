"""GET /api/map/assets — the assets covering a point or overlapping an area.

The catalog is faked at its own boundary because tests have no real `kb`
(context/integrations/kb.md). What is checked is what the endpoint decides:
which question it asks, with which geometry, and what it refuses.
"""

import pytest

from apps.catalog import kb

URL = "/api/map/assets"
AREA = "POLYGON((35.47 33.86, 35.55 33.86, 35.58 33.92, 35.50 33.94, 35.47 33.86))"


def row(asset_id, modality, uri):
    return {
        "asset_id": asset_id,
        "modality": modality,
        "source_uri": uri,
        "format": "parquet",
        "summary": None,
        "time_start": None,
        "time_end": None,
    }


ROWS = [
    row("aaaaaaaa-0000-0000-0000-000000000001", "raster", "s3://b/r.tif"),
    row("aaaaaaaa-0000-0000-0000-000000000002", "vector", "s3://b/a.parquet"),
    row("aaaaaaaa-0000-0000-0000-000000000003", "vector", "s3://b/b.parquet"),
]


@pytest.fixture
def catalog(monkeypatch):
    """Records which question was asked, and answers it with the same rows."""
    asked = {}

    def by_point(lon, lat):
        asked["point"] = (lon, lat)
        return ROWS

    def by_area(wkt):
        asked["area"] = wkt
        return ROWS

    monkeypatch.setattr(kb, "assets_covering_point", by_point)
    monkeypatch.setattr(kb, "assets_overlapping_area", by_area)
    return asked


def test_requires_authentication(api):
    assert api.get(URL, {"lon": 35.5, "lat": 33.9}).status_code == 401


def test_a_point_asks_what_covers_it(as_viewer, catalog):
    response = as_viewer.get(URL, {"lon": 35.5, "lat": 33.9})

    assert response.status_code == 200
    assert catalog == {"point": (35.5, 33.9)}


def test_an_area_asks_what_overlaps_it(as_viewer, catalog):
    response = as_viewer.get(URL, {"area": AREA})

    assert response.status_code == 200
    assert "point" not in catalog
    assert catalog["area"].startswith("POLYGON((35.47 33.86, ")


def test_either_question_is_grouped_the_same_way(as_viewer, catalog):
    """One answer shape for both, so the panel does not need to know which it asked."""
    by_point = as_viewer.get(URL, {"lon": 35.5, "lat": 33.9}).json()
    by_area = as_viewer.get(URL, {"area": AREA}).json()

    assert by_point == by_area
    assert [group["data_type"] for group in by_area["groups"]] == ["raster", "vector"]
    assert len(by_area["groups"][1]["assets"]) == 2


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"lon": 35.5},
        {"lat": 33.9},
        {"lon": 35.5, "lat": 33.9, "area": AREA},
        {"lon": 35.5, "area": AREA},
        {"lon": 200, "lat": 33.9},
        {"area": "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"},
        {"area": "POINT(35.5 33.9)"},
    ],
    ids=[
        "nothing",
        "lon alone",
        "lat alone",
        "point and area",
        "half a point and an area",
        "longitude out of range",
        "self-crossing area",
        "not a polygon",
    ],
)
def test_anything_but_exactly_one_readable_place_is_400(as_viewer, catalog, params):
    assert as_viewer.get(URL, params).status_code == 400
    assert catalog == {}
