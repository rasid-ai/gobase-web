"""The summary read and the attribute filter, run against real GeoParquet files.

Nothing mocks DuckDB, as in `test_lake.py`. What is under test is what an
answer depends on (docs/adr/028): a count that is exact, a filter that means
what it says for each column type, and a caller who cannot reach the SQL.
"""

import json

import duckdb
import pytest

from apps.map import lake
from apps.map.lake import AttributeFilter, FilterRefused

from .conftest import write_covered_points, write_spread_points


def _write(path, select: str) -> str:
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")
    connection.execute(f"COPY ({select}) TO '{path}' (FORMAT PARQUET)")
    connection.close()
    return str(path)


# Five places, one degree apart, with one column of each kind a filter treats
# differently. Row 3 holds the awkward values: a null, a NaN, no date.
PLACES = """
    SELECT * FROM (VALUES
        (1, 'School',           'Tripoli', 10.5,          DATE '2020-01-01', true,  ST_Point(0, 0)),
        (2, 'school',           'Beirut',  20.0,          DATE '2021-06-01', false, ST_Point(1, 0)),
        (3, 'Hospital',         NULL,      'nan'::DOUBLE, NULL,              NULL,  ST_Point(2, 0)),
        (4, 'High School 100%', 'Saida',   30.0,          DATE '2022-01-01', true,  ST_Point(3, 0)),
        (5, 'pre_school',       'Tyre',    NULL,          DATE '2023-01-01', false, ST_Point(4, 0))
    ) AS t(id, kind, city, score, opened, open, geometry)
"""


@pytest.fixture
def places(tmp_path):
    return _write(tmp_path / "places.parquet", PLACES)


def summary(path, column=None, op=None, *values, **scope):
    asked = AttributeFilter(column, op, tuple(values)) if column else None
    return lake.summarize_vector_features(path, sample=10, attribute_filter=asked, **scope)


def ids(result) -> list[int]:
    return [row["id"] for row in result["sample"]]


# --- the count ---------------------------------------------------------------


def test_the_whole_file_is_counted_with_no_place(places):
    result = summary(places)

    assert result["total"] == 5
    assert ids(result) == [1, 2, 3, 4, 5]


def test_the_sample_is_properties_only_in_file_order(places):
    result = lake.summarize_vector_features(places, sample=2)

    assert result["total"] == 5
    assert result["sample"] == [
        {
            "id": 1,
            "kind": "School",
            "city": "Tripoli",
            "score": 10.5,
            "opened": "2020-01-01",
            "open": True,
        },
        {
            "id": 2,
            "kind": "school",
            "city": "Beirut",
            "score": 20.0,
            "opened": "2021-06-01",
            "open": False,
        },
    ]


def test_a_sample_of_zero_still_counts(places):
    assert lake.summarize_vector_features(places, sample=0) == {"total": 5, "sample": []}


def test_nan_in_a_sample_is_null_so_the_body_is_json(places):
    result = summary(places, "id", "equals", "3")

    assert result["sample"][0]["score"] is None
    # What DRF's renderer would refuse, or a browser: a bare NaN.
    json.dumps(result, allow_nan=False)


def test_the_covering_column_is_never_in_a_sample(tmp_path):
    path = write_covered_points(tmp_path / "covered.parquet", rows=50)

    result = lake.summarize_vector_features(path, sample=1, bbox=(10.0, -0.5, 13.0, 0.5))

    assert result["total"] == 4
    assert result["sample"] == [{"osm_id": 10, "name": "feature-10"}]


def test_nothing_matching_is_zero_and_an_empty_sample(places):
    assert summary(places, bbox=(100.0, 40.0, 101.0, 41.0)) == {"total": 0, "sample": []}


# A line from corner to corner of a ten-degree square. Its bounding box is the
# whole square; the line itself only touches the diagonal.
DIAGONAL = """
    SELECT 1 AS id, ST_GeomFromText('LINESTRING(0 0, 10 10)') AS geometry,
           {'xmin': 0.0, 'ymin': 0.0, 'xmax': 10.0, 'ymax': 10.0} AS bbox
"""
# A rectangle in the square's corner, well away from the diagonal.
OFF_THE_LINE = (6.0, 0.0, 10.0, 4.0)


def test_a_bbox_is_counted_by_real_geometry_not_by_boxes(tmp_path):
    """The reason the summary exists: `/data` would call this one feature."""
    path = _write(tmp_path / "diagonal.parquet", DIAGONAL)

    drawn = lake.read_vector_features(path, limit=10, bbox=OFF_THE_LINE)
    counted = lake.summarize_vector_features(path, sample=5, bbox=OFF_THE_LINE)

    assert drawn["count"] == 1  # boxes overlap: fine for drawing
    assert counted == {"total": 0, "sample": []}  # the line is not there


def test_a_bbox_the_shape_does_cross_counts_it(tmp_path):
    path = _write(tmp_path / "diagonal.parquet", DIAGONAL)

    assert lake.summarize_vector_features(path, sample=0, bbox=(4.0, 4.0, 6.0, 6.0))["total"] == 1


def test_an_area_is_counted_exactly(tmp_path):
    path = _write(tmp_path / "diagonal.parquet", DIAGONAL)
    triangle = "POLYGON((6 0, 10 0, 10 4, 6 0))"

    result = lake.summarize_vector_features(
        path, sample=5, bbox=(6.0, 0.0, 10.0, 4.0), area=triangle
    )

    assert result["total"] == 0


def test_an_area_without_its_envelope_is_a_programming_error(places):
    with pytest.raises(ValueError, match="envelope"):
        lake.summarize_vector_features(places, sample=1, area="POLYGON((0 0, 1 0, 1 1, 0 0))")


def test_a_covered_file_and_a_plain_one_count_the_same(tmp_path):
    covered = write_covered_points(tmp_path / "covered.parquet", rows=200)
    plain = write_spread_points(tmp_path / "plain.parquet", rows=200)
    window = (10.0, -0.5, 13.0, 0.5)

    assert (
        lake.summarize_vector_features(covered, sample=0, bbox=window)["total"]
        == lake.summarize_vector_features(plain, sample=0, bbox=window)["total"]
        == 4
    )


# --- each operator -----------------------------------------------------------


def test_equals_on_text_ignores_case(places):
    assert ids(summary(places, "kind", "equals", "SCHOOL")) == [1, 2]


def test_equals_on_a_number_compares_the_value(places):
    assert ids(summary(places, "score", "equals", "20")) == [2]
    assert ids(summary(places, "id", "equals", "4")) == [4]


def test_a_fraction_against_a_whole_number_column_is_not_rounded(places):
    """`1.5` cast to an integer is 2. It must not find row 2, and 2 is greater than it."""
    assert ids(summary(places, "id", "equals", "1.5")) == []
    assert ids(summary(places, "id", ">", "1.5")) == [2, 3, 4, 5]
    assert ids(summary(places, "id", "in", "1.0", "2.5")) == [1]


def test_a_whole_number_too_large_for_the_column_matches_nothing(places):
    assert summary(places, "id", "equals", "9" * 30)["total"] == 0
    assert summary(places, "id", "<", "9" * 30)["total"] == 5


def test_a_large_id_is_compared_exactly(tmp_path):
    """Two 64-bit ids that are the same DOUBLE: each finds only itself."""
    path = _write(
        tmp_path / "ids.parquet",
        "SELECT * FROM (VALUES (9007199254740993, ST_Point(0, 0)), "
        "(9007199254740992, ST_Point(1, 0))) AS t(osm_id, geometry)",
    )

    assert summary(path, "osm_id", "equals", "9007199254740993")["total"] == 1


def test_a_large_id_stays_exact_beside_other_values(tmp_path):
    """One value that is not a whole number must not turn the list into DOUBLEs."""
    path = _write(
        tmp_path / "ids.parquet",
        "SELECT * FROM (VALUES (9007199254740993, ST_Point(0, 0)), "
        "(9007199254740992, ST_Point(1, 0))) AS t(osm_id, geometry)",
    )

    assert summary(path, "osm_id", "in", "9007199254740993", "1.5")["total"] == 1
    assert summary(path, "osm_id", "in", "9007199254740993", "9" * 20)["total"] == 1
    assert summary(path, "osm_id", "equals", "9007199254740993.0")["total"] == 1
    assert summary(path, "osm_id", "in", "9007199254740993", "9007199254740992")["total"] == 2
    assert summary(path, "osm_id", "in", "1.5", "9" * 30)["total"] == 0


@pytest.fixture
def singles(tmp_path):
    """A 32-bit FLOAT column: its 0.1 is not the DOUBLE 0.1."""
    return _write(
        tmp_path / "singles.parquet",
        "SELECT * FROM (VALUES "
        "(1, 0.1::FLOAT, ST_Point(0, 0)), "
        "(2, 0.5::FLOAT, ST_Point(1, 0)), "
        "(3, 16777216::FLOAT, ST_Point(2, 0)), "
        "(4, 'nan'::FLOAT, ST_Point(3, 0))"
        ") AS t(id, height, geometry)",
    )


def test_equals_and_in_on_a_single_precision_column(singles):
    assert ids(summary(singles, "height", "equals", "0.1")) == [1]
    assert ids(summary(singles, "height", "equals", "0.5")) == [2]
    assert ids(summary(singles, "height", "in", "0.1", "0.5")) == [1, 2]
    assert ids(summary(singles, "height", "equals", "16777216")) == [3]


def test_less_and_greater_on_a_single_precision_column(singles):
    """0.1 is neither less nor greater than 0.1, and NaN is neither."""
    assert ids(summary(singles, "height", ">", "0.1")) == [2, 3]
    assert ids(summary(singles, "height", "<", "0.1")) == []
    assert ids(summary(singles, "height", "<", "0.5")) == [1]


def test_a_number_too_large_for_single_precision_matches_nothing(singles):
    assert summary(singles, "height", "equals", "1e300")["total"] == 0
    assert ids(summary(singles, "height", "<", "1e300")) == [1, 2, 3]


def test_equals_on_a_date_and_a_boolean(places):
    assert ids(summary(places, "opened", "equals", "2021-06-01")) == [2]
    assert ids(summary(places, "open", "equals", "true")) == [1, 4]


def test_contains_ignores_case(places):
    assert ids(summary(places, "kind", "contains", "SCHOOL")) == [1, 2, 4, 5]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("%", [4]), ("_", [5]), ("100%", [4]), ("sch%l", [])],
    ids=["percent", "underscore", "percent in a word", "percent as a wildcard"],
)
def test_wildcards_in_contains_are_ordinary_characters(places, value, expected):
    assert ids(summary(places, "kind", "contains", value)) == expected


def test_in_matches_any_of_its_values(places):
    assert ids(summary(places, "city", "in", "tripoli", "SAIDA", "nowhere")) == [1, 4]
    assert ids(summary(places, "id", "in", "1", "5")) == [1, 5]


def test_less_and_greater_on_numbers(places):
    assert ids(summary(places, "score", "<", "20")) == [1]
    assert ids(summary(places, "id", ">", "3")) == [4, 5]


def test_less_and_greater_on_dates(places):
    assert ids(summary(places, "opened", ">", "2021-06-01")) == [4, 5]
    assert ids(summary(places, "opened", "<", "2021-01-01")) == [1]


def test_a_null_never_matches(places):
    """Row 3 has no city and row 5 no score: neither is equal to, or beyond, anything."""
    assert 3 not in ids(summary(places, "city", "contains", "a"))
    assert ids(summary(places, "score", ">", "-1000")) == [1, 2, 4]
    assert ids(summary(places, "score", "<", "1000")) == [1, 2, 4]


def test_nan_is_not_greater_than_a_number(places):
    """DuckDB sorts NaN above every number; an answer must not call it "more than 25"."""
    assert ids(summary(places, "score", ">", "25")) == [4]


def test_a_filter_and_a_place_narrow_together(places):
    result = summary(places, "kind", "contains", "school", bbox=(0.5, -1.0, 3.5, 1.0))

    assert ids(result) == [2, 4]
    assert result["total"] == 2


def test_a_page_takes_the_same_filter_as_the_count(places):
    """The map draws what was counted: same rows from both reads."""
    asked = AttributeFilter("kind", "contains", ("school",))

    page = lake.read_vector_features(places, limit=100, attribute_filter=asked)
    counted = lake.summarize_vector_features(places, sample=10, attribute_filter=asked)

    drawn = [f["properties"]["id"] for f in json.loads(page["features_json"])]
    assert drawn == ids(counted) == [1, 2, 4, 5]
    assert page["count"] == counted["total"] == 4


def test_a_filtered_page_still_pages(places):
    asked = AttributeFilter("kind", "contains", ("school",))

    first = lake.read_vector_features(places, limit=3, attribute_filter=asked)
    second = lake.read_vector_features(
        places, limit=3, attribute_filter=asked, cursor=first["next_cursor"]
    )

    assert first["count"] == 3 and first["next_cursor"] is not None
    assert [f["properties"]["id"] for f in json.loads(second["features_json"])] == [5]
    assert second["next_cursor"] is None


# --- each refusal ------------------------------------------------------------


def refusal(path, column, op, *values) -> FilterRefused:
    with pytest.raises(FilterRefused) as raised:
        summary(path, column, op, *values)
    return raised.value


def test_an_unknown_column_is_refused_and_the_real_ones_are_listed(places):
    refused = refusal(places, "name", "equals", "x")

    assert refused.field == "filter_column"
    assert refused.message == (
        "This asset has no column `name`. Its columns: id, kind, city, score, opened, open."
    )


@pytest.mark.parametrize("column", ["geometry", "bbox", "file_row_number"])
def test_the_files_structure_is_not_a_column_to_filter_on(tmp_path, column):
    path = write_covered_points(tmp_path / "covered.parquet", rows=5)

    refused = refusal(path, column, "equals", "1")

    assert refused.field == "filter_column"
    assert "Its columns: osm_id, name." in refused.message


def test_a_column_name_is_matched_exactly(places):
    assert refusal(places, "Kind", "equals", "school").field == "filter_column"


@pytest.mark.parametrize("op", ["<", ">"])
def test_less_and_greater_are_refused_on_text(places, op):
    refused = refusal(places, "kind", op, "m")

    assert refused.field == "filter_op"
    assert "needs a number or a date" in refused.message


def test_less_and_greater_are_refused_on_a_boolean(places):
    assert refusal(places, "open", ">", "false").field == "filter_op"


@pytest.mark.parametrize("column", ["score", "opened", "open"])
def test_contains_is_refused_on_anything_but_text(places, column):
    refused = refusal(places, column, "contains", "1")

    assert refused.field == "filter_op"
    assert "text columns" in refused.message


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("score", "many"),
        ("score", "nan"),
        ("score", "inf"),
        ("id", "1.5.2"),
        ("id", ""),
        ("opened", "last year"),
        ("open", "maybe"),
    ],
)
def test_a_value_that_is_not_of_the_columns_type_is_refused(places, column, value):
    refused = refusal(places, column, "equals", value)

    assert refused.field == "filter_value"
    assert "can hold" in refused.message


def test_one_bad_value_among_several_refuses_the_lot(places):
    assert refusal(places, "id", "in", "1", "two").field == "filter_value"


def test_an_operator_outside_the_list_is_refused(places):
    assert refusal(places, "kind", "like", "s%").field == "filter_op"


@pytest.mark.parametrize("op", ["equals", "contains", "<", ">"])
def test_only_in_takes_several_values(places, op):
    assert refusal(places, "kind", op, "a", "b").field == "filter_value"


def test_in_takes_at_most_twenty_values(places):
    values = [str(n) for n in range(lake.MAX_FILTER_VALUES + 1)]

    assert refusal(places, "id", "in", *values).field == "filter_value"
    assert summary(places, "id", "in", *values[:-1])["total"] == 5


def test_a_value_is_at_most_two_hundred_characters(places):
    assert refusal(places, "kind", "equals", "x" * 201).field == "filter_value"
    assert summary(places, "kind", "equals", "x" * 200)["total"] == 0


def test_no_value_and_an_empty_contains_are_refused(places):
    assert refusal(places, "kind", "equals").field == "filter_value"
    assert refusal(places, "kind", "contains", "").field == "filter_value"


@pytest.mark.parametrize(
    "select",
    [
        "SELECT {'a': 1} AS odd, ST_Point(0, 0) AS geometry",
        "SELECT [1, 2] AS odd, ST_Point(0, 0) AS geometry",
        "SELECT MAP {'a': 1} AS odd, ST_Point(0, 0) AS geometry",
        "SELECT 'ab'::BLOB AS odd, ST_Point(0, 0) AS geometry",
    ],
    ids=["struct", "list", "map", "blob"],
)
def test_a_nested_or_binary_column_cannot_be_filtered(tmp_path, select):
    path = _write(tmp_path / "odd.parquet", select)

    refused = refusal(path, "odd", "equals", "1")

    assert refused.field == "filter_column"
    assert "cannot be filtered on" in refused.message


# --- the caller cannot reach the SQL -----------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "kind\" = 'School' OR \"id",
        "kind; DROP TABLE x; --",
        "1=1) OR (1",
        "kind' OR '1'='1",
    ],
)
def test_sql_in_the_column_is_only_an_unknown_column(places, column):
    refused = refusal(places, column, "equals", "School")

    assert refused.field == "filter_column"
    assert refused.message.startswith("This asset has no column")


@pytest.mark.parametrize(
    "value",
    ["School' OR '1'='1", "x') OR 1=1 --", "'; DROP TABLE x; --", "\\' OR 1=1"],
)
@pytest.mark.parametrize("op", ["equals", "contains", "in"])
def test_sql_in_a_text_value_is_only_text_that_matches_nothing(places, op, value):
    assert summary(places, "kind", op, value) == {"total": 0, "sample": []}


def test_sql_in_a_number_value_is_refused_not_run(places):
    assert refusal(places, "id", "equals", "1 OR 1=1").field == "filter_value"
    assert refusal(places, "id", "<", "9); SELECT 1; --").field == "filter_value"


def test_column_names_that_need_quoting_can_be_filtered(tmp_path):
    """Real files have names like `fill-opacity`; a name is quoted, never pasted."""
    path = _write(
        tmp_path / "names.parquet",
        """
        SELECT * FROM (VALUES
            (0.5, 'x"y', 'first',  ST_Point(0, 0)),
            (0.9, 'z',   'second', ST_Point(1, 0))
        ) AS t("fill-opacity", "quo""te", "a b; c", geometry)
        """,
    )

    assert summary(path, "fill-opacity", ">", "0.6")["sample"][0]["a b; c"] == "second"
    assert summary(path, 'quo"te', "equals", 'X"Y')["total"] == 1
    assert summary(path, "a b; c", "contains", "IRS")["total"] == 1


def test_a_decimal_and_a_timestamp_column_take_a_filter(tmp_path):
    path = _write(
        tmp_path / "typed.parquet",
        """
        SELECT * FROM (VALUES
            (1.25::DECIMAL(10, 2), TIMESTAMPTZ '2020-09-04 11:58:40+00', ST_Point(0, 0)),
            (9.75::DECIMAL(10, 2), TIMESTAMPTZ '2024-01-01 00:00:00+00', ST_Point(1, 0))
        ) AS t(price, changed, geometry)
        """,
    )

    assert summary(path, "price", ">", "5")["total"] == 1
    assert summary(path, "price", "equals", "1.25")["total"] == 1
    assert summary(path, "changed", "<", "2022-01-01")["total"] == 1


# --- failures ----------------------------------------------------------------


def test_a_missing_file_is_a_read_error(tmp_path):
    with pytest.raises(lake.LakeReadError):
        lake.summarize_vector_features(str(tmp_path / "nope.parquet"), sample=1)
