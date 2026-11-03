"""The chunk index reader, run against a real local Lance table.

Nothing mocks lancedb. A local directory exercises the same code an s3:// URI
does — only the storage options differ — so the search, the prefilter, the
scoring and the box parsing are covered for real, the way `test_lake.py`
covers DuckDB with real GeoParquet.
"""

import pytest

from apps.catalog import chunks

TABLE = "BAAI_bge-small-en-v1.5"

# Three passages in two documents, with unit vectors in three dimensions so
# the ranking is readable: the query [1, 0, 0] is closest to `a`, then `b`.
ROWS = [
    {
        "chunk_id": "a",
        "asset_id": "doc-1",
        "doc_id": "sha-1",
        "ord": 0,
        "text": "Screening at the checkpoint.",
        "token_count": 5,
        "chunk_type": "text",
        "heading_path": ["3 Security", "3.2 Checkpoints"],
        "page_start": 2,
        "page_end": 2,
        "bboxes": '[{"page": 2, "bbox": [100, 200, 900, 260]}]',
        "vector": [1.0, 0.0, 0.0],
    },
    {
        "chunk_id": "b",
        "asset_id": "doc-2",
        "doc_id": "sha-2",
        "ord": 0,
        "text": "Runway lighting.",
        "token_count": 2,
        "chunk_type": "text",
        "heading_path": [],
        "page_start": 0,
        "page_end": 1,
        "bboxes": (
            '[{"page": 0, "bbox": [0, 900, 500, 1000]}, {"page": 1, "bbox": [0, 0, 500, 80]}]'
        ),
        "vector": [0.8, 0.6, 0.0],
    },
    {
        "chunk_id": "c",
        "asset_id": "doc-1",
        "doc_id": "sha-1",
        "ord": 1,
        "text": "Unrelated.",
        "token_count": 1,
        "chunk_type": "table",
        "heading_path": [],
        "page_start": None,
        "page_end": None,
        "bboxes": None,
        "vector": [0.0, 0.0, 1.0],
    },
]


@pytest.fixture
def chunks_uri(tmp_path):
    """A table where the catalog would point, as `doc_documents.chunks_uri` names one."""
    import lancedb

    lancedb.connect(str(tmp_path)).create_table(TABLE, data=ROWS)
    return f"{tmp_path}/{TABLE}.lance"


@pytest.fixture(autouse=True)
def _fresh_connections():
    chunks.reset()
    yield
    chunks.reset()


class TestStorageOptions:
    """Built from the lake's settings, the same ones DuckDB reads."""

    def test_nothing_configured_passes_nothing(self, settings):
        settings.LAKE_S3_ENDPOINT = ""
        settings.LAKE_S3_REGION = ""
        settings.LAKE_S3_ACCESS_KEY = ""
        settings.LAKE_S3_SECRET_KEY = ""

        # None, not {}: lancedb then uses the ambient credentials.
        assert chunks.storage_options() is None

    def test_a_local_store_over_http_with_path_style(self, settings):
        settings.LAKE_S3_ENDPOINT = "127.0.0.1:9000"
        settings.LAKE_S3_USE_SSL = False
        settings.LAKE_S3_URL_STYLE = "path"
        settings.LAKE_S3_REGION = ""
        settings.LAKE_S3_ACCESS_KEY = "key"
        settings.LAKE_S3_SECRET_KEY = "secret"

        assert chunks.storage_options() == {
            "aws_endpoint": "http://127.0.0.1:9000",
            "aws_virtual_hosted_style_request": "false",
            "allow_http": "true",
            "aws_access_key_id": "key",
            "aws_secret_access_key": "secret",
        }

    def test_aws_with_a_region_and_an_instance_role(self, settings):
        settings.LAKE_S3_ENDPOINT = ""
        settings.LAKE_S3_REGION = "eu-central-1"
        settings.LAKE_S3_ACCESS_KEY = ""
        settings.LAKE_S3_SECRET_KEY = ""

        assert chunks.storage_options() == {"aws_region": "eu-central-1"}

    def test_one_key_without_the_other_passes_neither(self, settings):
        settings.LAKE_S3_ENDPOINT = ""
        settings.LAKE_S3_REGION = ""
        settings.LAKE_S3_ACCESS_KEY = "key"
        settings.LAKE_S3_SECRET_KEY = ""

        assert chunks.storage_options() is None

    def test_ssl_endpoint_keeps_https_and_allows_no_http(self, settings):
        settings.LAKE_S3_ENDPOINT = "s3.example.net"
        settings.LAKE_S3_USE_SSL = True
        settings.LAKE_S3_URL_STYLE = "vhost"
        settings.LAKE_S3_REGION = ""
        settings.LAKE_S3_ACCESS_KEY = ""
        settings.LAKE_S3_SECRET_KEY = ""

        assert chunks.storage_options() == {"aws_endpoint": "https://s3.example.net"}


def test_the_table_is_named_by_the_uri_the_catalog_holds():
    uri = "s3://geobase-silver/index/chunks/BAAI_bge-small-en-v1.5.lance"

    assert chunks.table_location(uri) == ("s3://geobase-silver/index/chunks", TABLE)


def test_the_nearest_passages_come_best_first(chunks_uri):
    hits = chunks.search(chunks_uri, [1.0, 0.0, 0.0], ["doc-1", "doc-2"], k=10)

    assert [hit["chunk_id"] for hit in hits] == ["a", "b", "c"]
    assert hits[0]["score"] == pytest.approx(1.0)
    assert hits[1]["score"] == pytest.approx(0.8)
    assert hits[2]["score"] == pytest.approx(0.0)


def test_only_the_named_documents_are_searched(chunks_uri):
    hits = chunks.search(chunks_uri, [1.0, 0.0, 0.0], ["doc-2"], k=10)

    assert [hit["chunk_id"] for hit in hits] == ["b"]


def test_k_caps_the_answer(chunks_uri):
    assert len(chunks.search(chunks_uri, [1.0, 0.0, 0.0], ["doc-1", "doc-2"], k=2)) == 2


def test_no_documents_is_an_empty_answer_without_a_connection(tmp_path, monkeypatch):
    def refuse(directory):
        raise AssertionError("nothing to look in, so nothing should be opened")

    monkeypatch.setattr(chunks, "_connect", refuse)

    assert chunks.search(f"{tmp_path}/{TABLE}.lance", [1.0, 0.0, 0.0], [], k=5) == []


def test_a_table_the_bucket_does_not_hold_is_an_empty_answer(tmp_path):
    # The directory exists; the table does not. Not a failure: the data
    # platform's next run writes it.
    assert chunks.search(f"{tmp_path}/missing.lance", [1.0, 0.0, 0.0], ["doc-1"], k=5) == []


def test_a_hit_carries_no_vector_and_parsed_boxes(chunks_uri):
    (hit,) = chunks.search(chunks_uri, [0.8, 0.6, 0.0], ["doc-2"], k=1)

    assert "vector" not in hit
    assert "_distance" not in hit
    assert hit["text"] == "Runway lighting."
    assert hit["heading_path"] == []
    assert hit["page_start"] == 0
    assert hit["bboxes"] == [
        {"page": 0, "bbox": [0, 900, 500, 1000]},
        {"page": 1, "bbox": [0, 0, 500, 80]},
    ]


def test_no_boxes_is_an_empty_list(chunks_uri):
    (hit,) = chunks.search(chunks_uri, [0.0, 0.0, 1.0], ["doc-1"], k=1)

    assert hit["chunk_id"] == "c"
    assert hit["bboxes"] == []
    assert hit["page_start"] is None


@pytest.mark.parametrize(
    "raw",
    ["not json", "{}", '[{"page": "0", "bbox": [1, 2, 3, 4]}]', '[{"page": 0, "bbox": [1, 2]}]'],
    ids=["not json", "not a list", "page not an int", "box not four numbers"],
)
def test_boxes_that_are_not_boxes_are_dropped_not_raised(raw):
    assert chunks._boxes(raw, "x") == []


def test_one_passage_can_be_fetched_by_its_id(chunks_uri):
    hit = chunks.chunk(chunks_uri, "doc-1", "a")

    assert hit["text"] == "Screening at the checkpoint."
    assert hit["bboxes"] == [{"page": 2, "bbox": [100, 200, 900, 260]}]


def test_a_passage_of_another_document_is_not_found(chunks_uri):
    # The id is real, the document is wrong: a URL cannot read across documents.
    assert chunks.chunk(chunks_uri, "doc-2", "a") is None


def test_a_quote_in_an_id_cannot_break_out_of_the_filter(chunks_uri):
    assert chunks.chunk(chunks_uri, "doc-1", "a' OR chunk_id = 'b") is None
    assert chunks.search(chunks_uri, [1.0, 0.0, 0.0], ["doc-1' OR asset_id = 'doc-2"], k=5) == []


def test_an_unreachable_store_is_reported_by_type_only(tmp_path, monkeypatch):
    class Database:
        def open_table(self, name):
            raise OSError("http://127.0.0.1:9000 with key AKIA... refused")

    monkeypatch.setattr(chunks, "_connect", lambda directory: Database())

    with pytest.raises(chunks.ChunkStoreUnavailable) as failure:
        chunks.search(f"{tmp_path}/{TABLE}.lance", [1.0, 0.0, 0.0], ["doc-1"], k=5)

    # The endpoint and the key id must not travel in the exception.
    assert str(failure.value) == "OSError"
