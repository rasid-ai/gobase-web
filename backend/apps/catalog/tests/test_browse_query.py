"""How the browse query is assembled.

Tests have no real `kb` (context/integrations/kb.md), so the SQL cannot be run
here. What can be checked is the part that decides what the SQL says: which
clauses a filter adds, what it binds, and the ordering — none of which touch a
database.
"""

import pytest

from apps.catalog import kb


def test_no_filters_adds_no_clause():
    where, params = kb._where(None, None, None, None)
    assert (where, params) == ("", [])


def test_search_text_becomes_a_contains_match():
    where, params = kb._where("natural", None, None, None)
    assert "name ILIKE %s" in where
    assert params == ["%natural%"]


def test_search_text_is_matched_literally():
    """Asset names are full of underscores, which ILIKE would read as any character."""
    _, params = kb._where("osm_natural", None, None, None)
    assert params == [r"%osm\_natural%"]

    _, params = kb._where("100%", None, None, None)
    assert params == [r"%100\%%"]


def test_data_types_bind_as_one_array():
    where, params = kb._where(None, ["vector", "raster"], None, None)
    assert "modality = ANY(%s)" in where
    assert params == [["vector", "raster"]]


def test_the_ingestion_window_is_half_open():
    """Inclusive at the start, exclusive at the end, so adjacent windows cannot overlap."""
    where, params = kb._where(None, None, "A", "B")
    assert "ingested_at >= %s" in where
    assert "ingested_at < %s" in where
    assert params == ["A", "B"]


def test_filters_combine_with_and():
    where, params = kb._where("osm", ["vector"], "A", None)
    assert where.startswith(" WHERE ")
    assert where.count(" AND ") == 2
    assert params == [r"%osm%", ["vector"], "A"]


@pytest.mark.parametrize("sort", sorted(kb.SORTS))
def test_every_sort_orders_by_a_real_column(sort):
    assert kb.SORTS[sort].split()[0] in {"ingested_at", "name", "modality"}


def test_a_sort_the_api_does_not_offer_never_reaches_sql():
    """The ordering is looked up, so it cannot be smuggled in as text."""
    with pytest.raises(KeyError):
        kb.SORTS["bytes; DROP TABLE assets"]


def test_a_row_with_no_coverage_has_no_box():
    row = _row(min_lon=None, min_lat=None, max_lon=None, max_lat=None)
    assert kb._list_item(row)["bbox"] is None


def test_coverage_becomes_a_bbox_in_lon_lat_order():
    item = kb._list_item(_row())
    assert item["bbox"] == [13.5389, 50.9581, 14.0149, 51.198]


def test_the_modality_column_is_reported_as_the_data_type():
    """One word for one thing: the API says data_type everywhere."""
    item = kb._list_item(_row())
    assert item["data_type"] == "vector"
    assert "modality" not in item


def test_the_source_path_does_not_survive_into_a_list_row():
    assert "source_uri" not in kb._list_item(_row())


def _row(**overrides):
    return {
        "asset_id": "cd8173bb-65ef-4bab-8bec-2be34d7157b9",
        "name": "gis_osm_boundaries_07_1",
        "modality": "vector",
        "format": "geoparquet",
        "topic_path": "shapefiles_dresden",
        "bytes": 238368,
        "min_lon": 13.5389,
        "min_lat": 50.9581,
        "max_lon": 14.0149,
        "max_lat": 51.198,
        "summary": None,
        "time_start": None,
        "time_end": None,
        "ingested_at": "2026-09-09T11:02:41Z",
        **overrides,
    }


@pytest.mark.parametrize("sort", sorted(kb.SORTS))
def test_every_ordering_ends_in_a_tiebreak(sort):
    """Without it, offset paging repeats and drops rows.

    Every asset in the live catalog was ingested in the same run and carries
    the same `ingested_at`, so the default sort alone cannot order them.
    """
    assert kb._order_by(sort).endswith(", asset_id")
