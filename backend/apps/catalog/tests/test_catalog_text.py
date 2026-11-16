"""The dataset label and the search text, run for real.

Tests have no `kb` (context/integrations/kb.md), but they do have Postgres: the
portal's own test database. Both expressions are plain SQL over a handful of
columns, so they run here against temporary tables shaped like the catalog's,
which vanish with the test's transaction. What they check is what string
assertions cannot — what Postgres actually makes of the regexes and the JSON
paths.
"""

import json

import pytest
from django.db import connection

from apps.catalog import kb

SEPARATOR = "\x1f"


def _label(dataset):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {kb._DATASET_LABEL} FROM (VALUES (%s)) AS t(dataset)", [dataset])
        return cursor.fetchone()[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("dataset", "label"),
    [
        ("points_of_interest_hotsom", "Points of interest hotsom"),
        ("esri_landcover_landuse", "Esri landcover landuse"),
        ("road-network", "Road network"),
        ("roadNetwork", "Road network"),
        ("boundaries", "Boundaries"),
        ("__main__cities__", "Main cities"),
        # The data's own spelling: the knowledge base is read-only.
        ("goverment", "Goverment"),
    ],
)
def test_a_dataset_label_is_spaced_and_in_sentence_case(dataset, label):
    assert _label(dataset) == label


@pytest.mark.django_db
def test_no_dataset_has_no_label():
    assert _label(None) is None


def _name(source_uri, pdf_uri):
    # One row of `assets` beside one row of `doc`, the way the real join lays
    # them out; a NULL `pdf_uri` is an asset with no document row.
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {kb._NAME} FROM (VALUES (%s)) AS assets(source_uri), "
            f"(VALUES (%s)) AS doc(pdf_uri)",
            [source_uri, pdf_uri],
        )
        return cursor.fetchone()[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("source_uri", "pdf_uri", "name"),
    [
        ("s3://silver/vector/b/roads.parquet", None, "roads"),
        ("s3://silver/raster/l/lulc_2019.tif", None, "lulc_2019"),
        # A document is named after its PDF, extension kept (docs/adr/027).
        (
            "s3://silver/documents/airports/plan.bundle.zip",
            "s3://bronze/raw/airports/Airport Plan.pdf",
            "Airport Plan.pdf",
        ),
        # No PDF recorded: the bundle's stem, with `.bundle` taken off too.
        ("s3://silver/documents/airports/plan.bundle.zip", None, "plan"),
    ],
)
def test_an_asset_is_named_after_its_path_and_a_document_after_its_pdf(source_uri, pdf_uri, name):
    assert _name(source_uri, pdf_uri) == name


def _format(format, pdf_uri):
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {kb._FORMAT} FROM (VALUES (%s)) AS assets(format), "
            f"(VALUES (%s)) AS doc(pdf_uri)",
            [format, pdf_uri],
        )
        return cursor.fetchone()[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("format", "pdf_uri", "shown"),
    [
        ("geoparquet", None, "geoparquet"),
        # A document's format is its file's, not the parser's (docs/adr/027).
        ("mineru", "s3://bronze/raw/airports/Airport Plan.PDF", "pdf"),
        # No PDF recorded, or a name with no extension: the column as it is.
        ("mineru", None, "mineru"),
        ("mineru", "s3://bronze/raw/airports/README", "mineru"),
    ],
)
def test_a_documents_format_is_its_files_not_its_parsers(format, pdf_uri, shown):
    assert _format(format, pdf_uri) == shown


@pytest.fixture
def catalog(db):
    """Temporary tables with the columns the search text reads, and one row each."""
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE assets (asset_id uuid, source_uri text, dataset text, "
            "topic_path text, format text, modality text, summary text)"
        )
        cursor.execute(
            "CREATE TEMP TABLE geo_layers (asset_id uuid, layer_name text, columns jsonb)"
        )
        cursor.execute(
            "CREATE TEMP TABLE geo_raster_layers (asset_id uuid, layer_name text, tags jsonb)"
        )
        cursor.execute(
            "CREATE TEMP TABLE doc_documents (asset_id uuid, title text, pages int, pdf_uri text)"
        )
        cursor.execute(
            "INSERT INTO assets VALUES "
            "('00000000-0000-0000-0000-000000000001', 's3://silver/vector/b/roads.parquet', "
            "'road_network', 'road_network', 'geoparquet', 'vector', NULL), "
            "('00000000-0000-0000-0000-000000000002', 's3://silver/raster/l/lulc_2019.tif', "
            "'esri_landcover_landuse', 'esri_landcover_landuse', 'cog', 'raster', NULL), "
            "('00000000-0000-0000-0000-000000000003', "
            "'s3://silver/documents/airports/plan.bundle.zip', "
            "'airports', 'airports', 'mineru', 'document', 'The card text.')"
        )
        cursor.execute(
            "INSERT INTO doc_documents VALUES ('00000000-0000-0000-0000-000000000003', "
            "'Reopening the airport', 4, 's3://bronze/raw/airports/Airport Plan.pdf')"
        )
        cursor.execute(
            "INSERT INTO geo_layers VALUES ('00000000-0000-0000-0000-000000000001', 'roads', %s)",
            [
                json.dumps(
                    [{"name": "highway", "dtype": "string"}, {"name": "oneway", "dtype": "bool"}]
                )
            ],
        )
        cursor.execute(
            "INSERT INTO geo_raster_layers VALUES "
            "('00000000-0000-0000-0000-000000000002', 'lulc_2019', %s)",
            [
                json.dumps(
                    {
                        "default": {
                            "year": "2019",
                            "source": "Microsoft Planetary Computer STAC",
                            "classes": '{"1": "water", "2": "trees"}',
                        }
                    }
                )
            ],
        )


def _search_texts():
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT modality, {kb._SEARCH_TEXT} FROM assets {kb._DOCUMENTS} ORDER BY modality"
        )
        return {modality: text.split(SEPARATOR) for modality, text in cursor.fetchall()}


def test_a_document_is_searchable_by_its_pdf_name_and_its_title(catalog):
    """Neither is in `assets`; both are what a person would type."""
    fields = _search_texts()["document"]

    assert fields[:8] == [
        "plan.bundle.zip",
        "airports",
        "Airports",
        "airports",
        "mineru",
        "document",
        "The card text.",
        "Airport Plan.pdf",
    ]
    assert "Reopening the airport" in fields


def test_a_vector_asset_is_searchable_by_its_columns_but_not_by_their_json_keys(catalog):
    fields = _search_texts()["vector"]

    assert fields[:6] == [
        "roads.parquet",
        "road_network",
        "Road network",
        "road_network",
        "geoparquet",
        "vector",
    ]
    assert {"roads", "highway", "oneway"} <= set(fields)
    # A document cast to text would put these in every vector asset.
    assert "name" not in SEPARATOR.join(fields)
    assert "dtype" not in SEPARATOR.join(fields)


def test_a_raster_asset_is_searchable_by_tag_values_and_not_tag_keys(catalog):
    text = SEPARATOR.join(_search_texts()["raster"])

    assert "2019" in text
    assert "Microsoft Planetary Computer STAC" in text
    # A JSON document stored as text stays text: its words are still found.
    assert "water" in text
    # Every raster has a year; matching the key would find all of them.
    assert "year" not in text
    assert "default" not in text


def test_a_search_cannot_match_across_two_fields(catalog):
    """`vector` ends one field and a layer name starts the next: typed together, no match."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM assets {kb._DOCUMENTS} WHERE {kb._SEARCH_TEXT} ILIKE %s",
            [kb._contains("vector roads")],
        )
        assert cursor.fetchone()[0] == 0

        cursor.execute(
            f"SELECT count(*) FROM assets {kb._DOCUMENTS} WHERE {kb._SEARCH_TEXT} ILIKE %s",
            [kb._contains("HIGHWAY")],
        )
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(databases=["default", "kb"])
def test_json_columns_come_back_as_values_not_text():
    """Django hands psycopg's json and jsonb over as text; the catalog decodes them.

    Without this, a vector file's `columns` reached the client as one line of
    JSON text, and the detail pane could only print it.
    """
    (row,) = kb._rows(
        "SELECT %s::jsonb AS columns, %s::json AS tags, %s::text AS note",
        ['[{"name": "highway", "dtype": "string"}]', '{"year": "2019"}', '{"not": "decoded"}'],
    )

    assert row["columns"] == [{"name": "highway", "dtype": "string"}]
    assert row["tags"] == {"year": "2019"}
    # Text that happens to hold JSON is text: only JSON columns are decoded.
    assert row["note"] == '{"not": "decoded"}'
