"""GET /api/catalog/assets/similar — the map's Semantic mode (docs/adr/018).

Both boundaries are faked: the embedding service at `godoc.embed`, and the
card search at `kb.similar_assets`, since tests have no real `kb`
(context/integrations/kb.md). What is under test is the view: that the
question is embedded first and matched by the model that embedded it, what a
bad parameter does, and the shape that comes back.
"""

import pytest

from apps.catalog import godoc, kb

URL = "/api/catalog/assets/similar"
MODEL = "BAAI/bge-small-en-v1.5"
VECTOR = [0.1, 0.2, 0.3]


def match(**overrides):
    return {
        "asset_id": "b9bb3097-9feb-4805-b4b3-aed8d25fbada",
        "name": "Beirut airport - Case Study - TiSO.pdf",
        "data_type": "document",
        "format": "mineru",
        "dataset": "airports",
        "dataset_label": "Airports",
        "topic_path": "airports",
        "bytes": 0,
        "bbox": None,
        "summary": "A case study.",
        "time_start": None,
        "time_end": None,
        "ingested_at": "2026-10-19T11:02:41Z",
        "document": {"title": "TISO solutions", "pages": 8, "pdf": True},
        "score": 0.71,
        "dataset_bbox": None,
        **overrides,
    }


@pytest.fixture
def configured(settings):
    settings.GODOC_URL = "http://godoc:8003"


@pytest.fixture
def embedded(monkeypatch):
    """Replace the embedding call and record every question it was given."""
    questions = []

    def fake(text):
        questions.append(text)
        return MODEL, VECTOR

    monkeypatch.setattr(godoc, "embed", fake)
    return questions


@pytest.fixture
def searched(monkeypatch):
    """Replace the card search and record what the view asked it for."""
    asked = {}

    def fake(vector, embedder_id, limit):
        asked.update(vector=vector, embedder_id=embedder_id, limit=limit)
        return [match()]

    monkeypatch.setattr(kb, "similar_assets", fake)
    return asked


def test_requires_a_session(api):
    assert api.get(URL, {"q": "airport security"}).status_code == 401


def test_a_question_is_embedded_then_matched_by_the_same_model(
    as_viewer, configured, embedded, searched
):
    response = as_viewer.get(URL, {"q": "airport security"})

    assert response.status_code == 200
    assert embedded == ["airport security"]
    # The model the service reports is the one the cards are filtered on: a
    # second model's cards would rank nonsense against this vector.
    assert searched == {"vector": VECTOR, "embedder_id": MODEL, "limit": 10}

    body = response.data
    assert body["embedder"] == MODEL
    (found,) = body["results"]
    assert found["name"] == "Beirut airport - Case Study - TiSO.pdf"
    assert found["score"] == 0.71
    assert found["dataset_bbox"] is None
    assert found["document"] == {"title": "TISO solutions", "pages": 8, "pdf": True}
    assert "source_uri" not in found


def test_a_datasets_coverage_comes_back_as_four_numbers(
    as_viewer, configured, embedded, monkeypatch
):
    box = [35.1, 33.0, 36.6, 34.7]
    monkeypatch.setattr(kb, "similar_assets", lambda *_: [match(dataset_bbox=box)])

    (found,) = as_viewer.get(URL, {"q": "roads"}).data["results"]

    assert found["dataset_bbox"] == box


def test_a_limit_reaches_the_search(as_viewer, configured, embedded, searched):
    as_viewer.get(URL, {"q": "airport security", "limit": "3"})
    assert searched["limit"] == 3


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "x", "limit": "0"},
        {"q": "x", "limit": "51"},
        {"q": "x" * 501},
    ],
    ids=["no text", "empty text", "blank text", "limit too small", "limit too large", "too long"],
)
def test_a_bad_parameter_is_refused_before_anything_is_called(
    as_viewer, configured, embedded, searched, params
):
    assert as_viewer.get(URL, params).status_code == 400
    assert embedded == []
    assert searched == {}


def test_no_service_configured_is_a_503_before_any_call(as_viewer, settings, embedded):
    settings.GODOC_URL = ""

    response = as_viewer.get(URL, {"q": "airport security"})

    assert response.status_code == 503
    assert embedded == []


def test_an_unreachable_service_is_a_503(as_viewer, configured, monkeypatch):
    def down(text):
        raise godoc.GoDocUnavailable("ConnectError")

    monkeypatch.setattr(godoc, "embed", down)

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 503


def test_a_refused_question_is_a_502(as_viewer, configured, monkeypatch):
    def refused(text):
        raise godoc.GoDocError("HTTP 400")

    monkeypatch.setattr(godoc, "embed", refused)

    assert as_viewer.get(URL, {"q": "airport security"}).status_code == 502


def test_nothing_close_is_an_empty_list_not_an_error(as_viewer, configured, embedded, monkeypatch):
    monkeypatch.setattr(kb, "similar_assets", lambda *_: [])

    response = as_viewer.get(URL, {"q": "something the catalog has nothing about"})

    assert response.status_code == 200
    assert response.data == {"embedder": MODEL, "results": []}
