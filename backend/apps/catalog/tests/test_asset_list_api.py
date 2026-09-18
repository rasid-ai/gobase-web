"""What GET /api/catalog/assets promises: specs/assets.md.

The browse query is faked at `kb.asset_list`, so what is under test here is the
view: which filters reach the knowledge base, what a bad parameter does, and
the shape that comes back.
"""

import pytest

URL = "/api/catalog/assets"


def test_browsing_requires_a_session(api):
    assert api.get(URL).status_code == 401


def test_no_filters_asks_for_everything(as_viewer, captured):
    assert as_viewer.get(URL).status_code == 200
    assert captured == {
        "q": None,
        "data_types": None,
        "bbox": None,
        "ingested_after": None,
        "ingested_before": None,
        "sort": "-ingested_at",
        "limit": 50,
        "offset": 0,
    }


def test_a_cleared_search_box_is_not_a_filter(as_viewer, captured):
    """`q=` is what the interface sends once the box is emptied."""
    assert as_viewer.get(URL, {"q": ""}).status_code == 200
    assert captured["q"] is None


def test_search_text_reaches_the_query(as_viewer, captured):
    as_viewer.get(URL, {"q": "natural"})
    assert captured["q"] == "natural"


def test_data_type_is_repeatable(as_viewer, captured):
    as_viewer.get(f"{URL}?data_type=vector&data_type=raster")
    assert captured["data_types"] == ["vector", "raster"]


def test_one_data_type_still_arrives_as_a_list(as_viewer, captured):
    as_viewer.get(f"{URL}?data_type=vector")
    assert captured["data_types"] == ["vector"]


def test_the_ingestion_window_reaches_the_query(as_viewer, captured):
    as_viewer.get(
        URL,
        {"ingested_after": "2026-09-01T00:00:00Z", "ingested_before": "2026-09-10T00:00:00Z"},
    )
    assert captured["ingested_after"].isoformat() == "2026-09-01T00:00:00+00:00"
    assert captured["ingested_before"].isoformat() == "2026-09-10T00:00:00+00:00"


@pytest.mark.parametrize("sort", ["-ingested_at", "ingested_at", "name", "-name", "data_type"])
def test_every_offered_sort_is_accepted(as_viewer, captured, sort):
    assert as_viewer.get(URL, {"sort": sort}).status_code == 200
    assert captured["sort"] == sort


def test_paging_reaches_the_query(as_viewer, captured):
    as_viewer.get(URL, {"limit": "10", "offset": "20"})
    assert (captured["limit"], captured["offset"]) == (10, 20)


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "bytes"},
        {"limit": "0"},
        {"limit": "201"},
        {"offset": "-1"},
        {"ingested_after": "last tuesday"},
    ],
    ids=["unknown sort", "limit too small", "limit too large", "negative offset", "bad date"],
)
def test_a_parameter_the_api_does_not_offer_is_rejected(as_viewer, captured, params):
    assert as_viewer.get(URL, params).status_code == 400
    assert captured == {}


def test_the_answer_carries_the_page_the_total_and_the_counts(as_viewer, monkeypatch):
    from apps.catalog import kb

    monkeypatch.setattr(
        kb,
        "asset_list",
        lambda **_: {
            "count": 22,
            "results": [
                {
                    "asset_id": "cd8173bb-65ef-4bab-8bec-2be34d7157b9",
                    "name": "gis_osm_boundaries_07_1",
                    "data_type": "vector",
                    "format": "geoparquet",
                    "topic_path": "shapefiles_dresden",
                    "bytes": 238368,
                    "bbox": [13.5389, 50.9581, 14.0149, 51.198],
                    "summary": None,
                    "time_start": None,
                    "time_end": None,
                    "ingested_at": "2026-09-09T11:02:41Z",
                }
            ],
            "data_type_counts": [{"data_type": "vector", "count": 22}],
        },
    )

    body = as_viewer.get(URL).data
    assert body["count"] == 22
    assert body["data_type_counts"] == [{"data_type": "vector", "count": 22}]

    (asset,) = body["results"]
    assert asset["name"] == "gis_osm_boundaries_07_1"
    assert asset["data_type"] == "vector"
    assert asset["bbox"] == [13.5389, 50.9581, 14.0149, 51.198]
    # Empty across the whole live catalog, and null rather than absent so the
    # interface can render one row shape for every asset.
    assert asset["summary"] is None
    assert asset["time_start"] is None
    # The bucket path never leaves the server on this endpoint.
    assert "source_uri" not in asset


def test_an_empty_catalog_is_an_answer_not_an_error(as_viewer, captured):
    body = as_viewer.get(URL).data
    assert body == {"count": 0, "results": [], "data_type_counts": []}


def test_an_area_reaches_the_query_as_four_numbers(as_viewer, captured):
    assert as_viewer.get(URL, {"bbox": "35.4,33.8,35.6,34.0"}).status_code == 200
    assert captured["bbox"] == [35.4, 33.8, 35.6, 34.0]


def test_a_zero_area_box_is_a_point_and_is_accepted(as_viewer, captured):
    # Asking what covers one spot is a real question, not a malformed one.
    assert as_viewer.get(URL, {"bbox": "35.5,33.9,35.5,33.9"}).status_code == 200
    assert captured["bbox"] == [35.5, 33.9, 35.5, 33.9]


@pytest.mark.parametrize(
    "bad",
    [
        "35.4,33.8,35.6",  # three numbers
        "35.4,33.8,35.6,34.0,1",  # five
        "a,b,c,d",  # not numbers
        "nan,33.8,35.6,34.0",  # float() takes it, PostGIS cannot use it
        "200,33.8,201,34.0",  # longitude out of range
        "35.4,-91,35.6,-92",  # latitude out of range
        "35.6,33.8,35.4,34.0",  # inside out
    ],
)
def test_a_malformed_area_is_rejected_before_the_query(as_viewer, captured, bad):
    assert as_viewer.get(URL, {"bbox": bad}).status_code == 400
    assert captured == {}


def test_a_cleared_area_is_not_a_filter(as_viewer, captured):
    # `bbox=` is what the URL holds for a moment while an area chip is being
    # removed, and it means the same as no area at all — the same way `q=`
    # means no search text.
    assert as_viewer.get(URL, {"bbox": ""}).status_code == 200
    assert captured["bbox"] is None
