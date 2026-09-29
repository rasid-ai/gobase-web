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


def test_search_text_becomes_a_contains_match_over_the_whole_catalog_text():
    """Not the name alone: the search reaches every field of metadata (docs/adr/016)."""
    where, params = kb._where("natural", None, None, None)
    assert "search ILIKE %s" in where
    assert "name ILIKE" not in where
    assert params == ["%natural%"]


def test_a_typed_field_separator_cannot_bridge_two_fields():
    """The separator keeps fields apart only if the search text cannot contain it."""
    _, params = kb._where("vector\x1fboundaries", None, None, None)
    assert params == ["%vectorboundaries%"]


def test_a_dataset_is_matched_exactly():
    """It names a dataset the caller picked, so it is a value, not a pattern."""
    where, params = kb._where(None, None, None, None, "points_of_interest")
    assert "dataset = %s" in where
    assert "ILIKE" not in where
    assert params == ["points_of_interest"]


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
    where, params = kb._where("osm", ["vector"], "A", None, "boundaries")
    assert where.startswith(" WHERE ")
    assert where.count(" AND ") == 3
    assert params == [r"%osm%", ["vector"], "boundaries", "A"]


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


def test_a_list_row_carries_its_dataset_and_its_label():
    item = kb._list_item(_row())
    assert item["dataset"] == "points_of_interest_hotsom"
    assert item["dataset_label"] == "Points of interest hotsom"


def test_the_search_text_itself_never_leaves_the_server():
    """It is a matching aid, and a list row that carried it would be twice the size."""
    assert "search" not in kb._list_item(_row(search="anything"))


def _row(**overrides):
    return {
        "asset_id": "cd8173bb-65ef-4bab-8bec-2be34d7157b9",
        "name": "gis_osm_boundaries_07_1",
        "modality": "vector",
        "format": "geoparquet",
        "dataset": "points_of_interest_hotsom",
        "dataset_label": "Points of interest hotsom",
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


AREA = "POLYGON((35.47 33.86, 35.55 33.86, 35.58 33.92, 35.50 33.94, 35.47 33.86))"


class TestPlace:
    """The place filter, which lives in the CTE so all three reads share it.

    A searched place's box, a clicked point, or a drawn area — one at most.
    """

    def test_no_place_adds_no_clause_and_binds_nothing(self):
        sql, params = kb._catalog(None)

        assert "ST_MakeEnvelope" not in sql
        assert "ST_MakePoint" not in sql
        assert "ST_GeomFromText" not in sql
        assert params == []

    def test_a_point_binds_longitude_first(self):
        sql, params = kb._catalog(point=(35.5, 33.9))

        assert "ST_Intersects(extent, ST_SetSRID(ST_MakePoint(%s, %s), 4326))" in sql
        assert params == [35.5, 33.9]

    def test_an_area_binds_its_polygon_as_one_parameter(self):
        sql, params = kb._catalog(area=AREA)

        assert "ST_Intersects(extent, ST_GeomFromText(%s, 4326))" in sql
        assert params == [AREA]

    def test_two_places_at_once_are_refused(self):
        # ANDing them would answer a question nobody asked.
        with pytest.raises(ValueError):
            kb._catalog([35.4, 33.8, 35.6, 34.0], point=(35.5, 33.9))

    def test_every_read_is_narrowed_by_the_point(self, run):
        kb.asset_list(point=(35.5, 33.9))

        assert len(run) == 3
        assert all("ST_MakePoint" in sql for sql, _ in run)

    def test_an_area_binds_its_corners_in_envelope_order(self):
        sql, params = kb._catalog([35.4, 33.8, 35.6, 34.0])

        assert "ST_Intersects(extent, ST_MakeEnvelope(%s, %s, %s, %s, 4326))" in sql
        # min_lon, min_lat, max_lon, max_lat — the order the URL carries and
        # the order ST_MakeEnvelope wants, so nothing is swapped between them.
        assert params == [35.4, 33.8, 35.6, 34.0]

    def test_every_read_is_narrowed_by_the_area(self, run):
        # The page, the total and the per-type counts all come off one CTE. A
        # grid showing nothing beside a rail still counting the whole catalog
        # reads as a broken page, so this is structural, not incidental.
        kb.asset_list(bbox=[35.4, 33.8, 35.6, 34.0])

        assert len(run) == 3
        assert all("ST_MakeEnvelope" in sql for sql, _ in run)

    def test_the_area_is_bound_before_the_other_filters(self, run):
        # The CTE's placeholders come first, then _where's, then the paging
        # pair. Wrong order binds numbers to the wrong placeholders and returns
        # a wrong answer rather than raising.
        kb.asset_list(bbox=[35.4, 33.8, 35.6, 34.0], q="osm", limit=12, offset=24)

        page_params = run[0][1]
        assert page_params == [35.4, 33.8, 35.6, 34.0, r"%osm%", 12, 24]

    def test_the_dataset_narrows_the_counts_too(self, run):
        # Unlike the data type selection, which the counts ignore on purpose:
        # inside a dataset, the counts describe that dataset.
        kb.asset_list(dataset="boundaries", data_types=["vector"], area=AREA)

        page, total, counts = run
        assert page[1][:3] == [AREA, ["vector"], "boundaries"]
        assert counts[1] == [AREA, "boundaries"]
        assert "modality = ANY" not in counts[0]


class TestDatasetList:
    """The first step of browsing by dataset."""

    @pytest.fixture
    def grouped(self, monkeypatch):
        """Answers with rows the way the grouped read returns them, and records the call."""
        calls = []

        def fake(sql, params):
            calls.append((sql, list(params)))
            return [
                _grouped("boundaries", "Boundaries", "unparsed", 4),
                _grouped("boundaries", "Boundaries", "vector", 5),
                _grouped("road_network", "Road network", "vector", 1),
            ]

        monkeypatch.setattr(kb, "_rows", fake)
        return calls

    def test_rows_fold_into_one_entry_per_dataset(self, grouped):
        assert kb.dataset_list() == [
            {
                "dataset": "boundaries",
                "label": "Boundaries",
                "count": 9,
                "data_type_counts": [
                    {"data_type": "unparsed", "count": 4},
                    {"data_type": "vector", "count": 5},
                ],
            },
            {
                "dataset": "road_network",
                "label": "Road network",
                "count": 1,
                "data_type_counts": [{"data_type": "vector", "count": 1}],
            },
        ]

    def test_an_asset_with_no_dataset_is_not_gathered_under_one(self, grouped):
        kb.dataset_list()

        ((sql, _),) = grouped
        assert "dataset IS NOT NULL" in sql

    def test_search_matches_the_name_or_the_label_and_never_the_files(self, grouped):
        kb.dataset_list(q="points of")

        ((sql, params),) = grouped
        assert "dataset ILIKE %s" in sql
        assert "dataset_label ILIKE %s" in sql
        assert "search ILIKE" not in sql
        assert params == ["%points of%", "%points of%"]

    def test_the_place_binds_first_and_the_window_before_the_search(self, grouped):
        kb.dataset_list(q="road", point=(35.5, 33.9), ingested_after="A")

        ((_, params),) = grouped
        assert params == [35.5, 33.9, "A", "%road%", "%road%"]

    def test_datasets_are_ordered_by_what_people_read(self, grouped):
        kb.dataset_list()

        ((sql, _),) = grouped
        assert "ORDER BY dataset_label" in sql


def _grouped(dataset, label, modality, count):
    return {"dataset": dataset, "dataset_label": label, "modality": modality, "count": count}


def test_a_detail_carries_the_catalog_name_beside_its_metadata(monkeypatch):
    """The list and the detail must call an asset the same thing."""
    answers = iter(
        [
            [
                {
                    "asset_id": "cd8173bb-65ef-4bab-8bec-2be34d7157b9",
                    "name": "lebanon_roads_full",
                    "modality": "vector",
                    "source_uri": "s3://silver/vector/road_network/lebanon_roads_full.parquet",
                    "format": "geoparquet",
                    "dataset": "road_network",
                    "summary": None,
                    "footprint": None,
                }
            ],
            [],
        ]
    )
    monkeypatch.setattr(kb, "_rows", lambda sql, params: next(answers))

    detail = kb.asset_detail("cd8173bb-65ef-4bab-8bec-2be34d7157b9")

    assert detail["name"] == "lebanon_roads_full"
    assert "name" not in detail["metadata"]
    assert detail["metadata"]["dataset"] == "road_network"
