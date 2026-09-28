"""What GET /api/catalog/datasets promises, and the place both endpoints share.

The dataset read is faked at `kb.dataset_list` and the asset read at
`kb.asset_list`, so what is under test is the view: which filters reach the
knowledge base, what a bad place does, and the shape that comes back.
"""

import pytest

URL = "/api/catalog/datasets"
AREA = "POLYGON((35.47 33.86, 35.55 33.86, 35.58 33.92, 35.50 33.94, 35.47 33.86))"


def test_listing_datasets_requires_a_session(api):
    assert api.get(URL).status_code == 401


def test_no_filters_asks_for_every_dataset(as_viewer, captured_datasets):
    assert as_viewer.get(URL).status_code == 200
    assert captured_datasets == {
        "q": None,
        "bbox": None,
        "point": None,
        "area": None,
        "ingested_after": None,
        "ingested_before": None,
    }


def test_search_text_reaches_the_query(as_viewer, captured_datasets):
    as_viewer.get(URL, {"q": "points of"})
    assert captured_datasets["q"] == "points of"


def test_a_cleared_search_box_is_not_a_filter(as_viewer, captured_datasets):
    as_viewer.get(URL, {"q": ""})
    assert captured_datasets["q"] is None


@pytest.mark.parametrize(
    ("params", "key", "value"),
    [
        ({"bbox": "35.4,33.8,35.6,34.0"}, "bbox", [35.4, 33.8, 35.6, 34.0]),
        ({"lon": 35.5, "lat": 33.9}, "point", (35.5, 33.9)),
    ],
    ids=["searched place", "clicked point"],
)
def test_each_kind_of_place_reaches_the_query(as_viewer, captured_datasets, params, key, value):
    assert as_viewer.get(URL, params).status_code == 200
    assert captured_datasets[key] == value


def test_a_drawn_area_reaches_the_query(as_viewer, captured_datasets):
    assert as_viewer.get(URL, {"area": AREA}).status_code == 200
    assert captured_datasets["area"].startswith("POLYGON((35.47 33.86, ")


def test_the_answer_lists_each_dataset_with_its_label_and_counts(as_viewer, monkeypatch):
    from apps.catalog import kb

    monkeypatch.setattr(
        kb,
        "dataset_list",
        lambda **_: [
            {
                "dataset": "boundaries",
                "label": "Boundaries",
                "count": 9,
                "data_type_counts": [
                    {"data_type": "unparsed", "count": 4},
                    {"data_type": "vector", "count": 5},
                ],
            }
        ],
    )

    body = as_viewer.get(URL).json()
    assert body == {
        "results": [
            {
                "dataset": "boundaries",
                "label": "Boundaries",
                "count": 9,
                "data_type_counts": [
                    {"data_type": "unparsed", "count": 4},
                    {"data_type": "vector", "count": 5},
                ],
            }
        ]
    }


def test_no_dataset_matching_is_an_answer_not_an_error(as_viewer, captured_datasets):
    assert as_viewer.get(URL).json() == {"results": []}


@pytest.mark.parametrize("url", [URL, "/api/catalog/assets"], ids=["datasets", "assets"])
@pytest.mark.parametrize(
    "params",
    [
        {"lon": 35.5},
        {"lat": 33.9},
        {"lon": 35.5, "lat": 33.9, "area": AREA},
        {"lon": 35.5, "lat": 33.9, "bbox": "35.4,33.8,35.6,34.0"},
        {"bbox": "35.4,33.8,35.6,34.0", "area": AREA},
        {"lon": 200, "lat": 33.9},
        {"area": "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"},
        {"area": "POINT(35.5 33.9)"},
    ],
    ids=[
        "lon alone",
        "lat alone",
        "point and area",
        "point and bbox",
        "bbox and area",
        "longitude out of range",
        "self-crossing area",
        "not a polygon",
    ],
)
def test_anything_but_one_readable_place_is_400(
    as_viewer, captured, captured_datasets, url, params
):
    assert as_viewer.get(url, params).status_code == 400
    assert captured == {}
    assert captured_datasets == {}
