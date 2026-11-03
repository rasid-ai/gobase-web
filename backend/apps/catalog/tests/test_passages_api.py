"""GET /api/catalog/passages — the Assets page's Semantic search (docs/adr/020).

Both boundaries are faked: the embedding service at `godoc.embed`, and the deep
search at `passages.search`, since tests have no real `kb` or chunk index. What
is under test is the view: that the question is embedded first and searched
with the model that embedded it, that the scope reaches the search, what a bad
parameter does, and the shape that comes back.
"""

import pytest

from apps.catalog import chunks, godoc, passages

URL = "/api/catalog/passages"
MODEL = "BAAI/bge-small-en-v1.5"
VECTOR = [0.1, 0.2, 0.3]


def found(**overrides):
    return {
        "asset_id": "b9bb3097-9feb-4805-b4b3-aed8d25fbada",
        "name": "Beirut airport - Case Study - TiSO.pdf",
        "data_type": "document",
        "format": "pdf",
        "dataset": "airports",
        "dataset_label": "Airports",
        "topic_path": "airports",
        "bytes": 0,
        "bbox": None,
        "summary": None,
        "time_start": None,
        "time_end": None,
        "ingested_at": "2026-10-19T11:02:41Z",
        "document": {"title": "TISO solutions", "pages": 8, "pdf": True},
        "score": 0.71,
        "passages": [
            {
                "chunk_id": "0a1b",
                "text": "Screening at the checkpoint.",
                "heading_path": ["3 Security", "3.2 Checkpoints"],
                "page_start": 3,
                "page_end": 3,
                "pages_with_boxes": [3],
                "chunk_type": "text",
                "score": 0.71,
            }
        ],
        **overrides,
    }


@pytest.fixture
def configured(settings):
    settings.GODOC_URL = "http://godoc:8003"


@pytest.fixture
def embedded(monkeypatch):
    questions = []

    def fake(text):
        questions.append(text)
        return MODEL, VECTOR

    monkeypatch.setattr(godoc, "embed", fake)
    return questions


@pytest.fixture
def searched(monkeypatch):
    """Replace the deep search and record what the view asked it for."""
    asked = {}

    def fake(vector, embedder_id, **kwargs):
        asked.update(vector=vector, embedder_id=embedder_id, **kwargs)
        return [found()]

    monkeypatch.setattr(passages, "search", fake)
    return asked


def test_requires_a_session(api):
    assert api.get(URL, {"q": "airport security"}).status_code == 401


def test_a_question_is_embedded_then_searched_by_the_same_model(
    as_viewer, configured, embedded, searched
):
    response = as_viewer.get(URL, {"q": "airport security"})

    assert response.status_code == 200
    assert embedded == ["airport security"]
    assert searched["vector"] == VECTOR
    assert searched["embedder_id"] == MODEL
    assert (searched["limit"], searched["per_document"]) == (10, 3)

    body = response.data
    assert body["embedder"] == MODEL
    (document,) = body["results"]
    assert document["name"] == "Beirut airport - Case Study - TiSO.pdf"
    assert document["score"] == 0.71
    assert "source_uri" not in document
    (passage,) = document["passages"]
    assert passage["chunk_id"] == "0a1b"
    assert passage["heading_path"] == ["3 Security", "3.2 Checkpoints"]
    assert passage["page_start"] == 3
    assert passage["pages_with_boxes"] == [3]


def test_the_scope_reaches_the_search(as_viewer, configured, embedded, searched):
    as_viewer.get(
        URL,
        {
            "q": "runways",
            "bbox": "35.4,33.8,35.6,34.1",
            "coverage": "dataset",
            "dataset": "airports",
            "ingested_after": "2026-09-01T00:00:00Z",
            "limit": "5",
            "passages": "2",
        },
    )

    assert searched["bbox"] == [35.4, 33.8, 35.6, 34.1]
    assert searched["coverage"] == "dataset"
    assert searched["point"] is None
    assert searched["area"] is None
    assert searched["dataset"] == "airports"
    assert searched["ingested_after"].isoformat() == "2026-09-01T00:00:00+00:00"
    assert (searched["limit"], searched["per_document"]) == (5, 2)


def test_a_cleared_dataset_is_not_a_filter(as_viewer, configured, embedded, searched):
    as_viewer.get(URL, {"q": "runways", "dataset": ""})
    assert searched["dataset"] is None


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "x" * 501},
        {"q": "x", "limit": "0"},
        {"q": "x", "limit": "51"},
        {"q": "x", "passages": "0"},
        {"q": "x", "passages": "11"},
        {"q": "x", "lon": "35.5"},
        {"q": "x", "bbox": "35.4,33.8,35.6,34.1", "lon": "35.5", "lat": "33.9"},
    ],
    ids=[
        "no text",
        "empty text",
        "blank text",
        "too long",
        "limit too small",
        "limit too large",
        "no passages",
        "too many passages",
        "half a point",
        "two places",
    ],
)
def test_a_bad_parameter_is_refused_before_anything_is_called(
    as_viewer, configured, embedded, searched, params
):
    assert as_viewer.get(URL, params).status_code == 400
    assert embedded == []
    assert searched == {}


def test_no_service_configured_is_a_503_before_any_call(as_viewer, settings, embedded, searched):
    settings.GODOC_URL = ""

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 503
    assert embedded == []
    assert searched == {}


def test_an_unreachable_embedding_service_is_a_503(as_viewer, configured, monkeypatch, searched):
    def down(text):
        raise godoc.GoDocUnavailable("ConnectError")

    monkeypatch.setattr(godoc, "embed", down)

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 503
    assert searched == {}


def test_a_refused_question_is_a_502(as_viewer, configured, monkeypatch):
    def refused(text):
        raise godoc.GoDocError("HTTP 400")

    monkeypatch.setattr(godoc, "embed", refused)

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 502


def test_an_unreachable_index_is_a_503(as_viewer, configured, embedded, monkeypatch):
    def down(*args, **kwargs):
        raise chunks.ChunkStoreUnavailable("OSError")

    monkeypatch.setattr(passages, "search", down)

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 503


def test_a_failed_index_search_is_a_502(as_viewer, configured, embedded, monkeypatch):
    def failed(*args, **kwargs):
        raise chunks.ChunkStoreError("ValueError")

    monkeypatch.setattr(passages, "search", failed)

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 502


def test_nothing_close_is_an_empty_list_not_an_error(as_viewer, configured, embedded, monkeypatch):
    monkeypatch.setattr(passages, "search", lambda *args, **kwargs: [])

    response = as_viewer.get(URL, {"q": "something the documents say nothing about"})

    assert response.status_code == 200
    assert response.data == {"embedder": MODEL, "results": []}
