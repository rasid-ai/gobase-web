"""GET /api/catalog/assets/{id}/passages/{chunk_id} — one passage, by its id.

The catalog is faked at `kb.document_chunks_uri` and the chunk index at
`chunks.chunk`, since tests have no real `kb` or bucket. What is under test is
the read between them: which table is asked, for which ids, what comes back,
and what each miss answers.
"""

import uuid

import pytest

from apps.catalog import chunks, kb

ASSET_ID = uuid.UUID("b9bb3097-9feb-4805-b4b3-aed8d25fbada")
TABLE = "s3://geobase-silver/index/chunks/BAAI_bge-small-en-v1.5.lance"
CHUNK_ID = "0a1b" * 8


def url(chunk_id=CHUNK_ID):
    return f"/api/catalog/assets/{ASSET_ID}/passages/{chunk_id}"


@pytest.fixture
def chunked(monkeypatch):
    """The catalog names a chunk table for the document."""
    monkeypatch.setattr(kb, "document_chunks_uri", lambda asset_id: TABLE)


@pytest.fixture
def passage(monkeypatch):
    """One passage in the index, on pages 3 and 4 to a reader (2 and 3 to the index)."""
    asked = []

    def fake(chunks_uri, asset_id, chunk_id):
        asked.append((chunks_uri, str(asset_id), chunk_id))
        if chunk_id != CHUNK_ID:
            return None
        return {
            "chunk_id": CHUNK_ID,
            "asset_id": str(asset_id),
            "doc_id": "0e2c" * 16,
            "ord": 7,
            "text": "Screening at the checkpoint.",
            "token_count": 5,
            "chunk_type": "text",
            "heading_path": ["3 Security", "3.2 Checkpoints"],
            "page_start": 2,
            "page_end": 3,
            "bboxes": [{"page": 2, "bbox": [0, 0, 500, 1000]}],
            "score": None,
        }

    monkeypatch.setattr(chunks, "chunk", fake)
    return asked


def test_requires_authentication(api):
    assert api.get(url()).status_code == 401


def test_returns_the_passage_with_pages_counted_from_one(as_viewer, chunked, passage):
    response = as_viewer.get(url())

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": str(ASSET_ID),
        "chunk_id": CHUNK_ID,
        "text": "Screening at the checkpoint.",
        "heading_path": ["3 Security", "3.2 Checkpoints"],
        "page_start": 3,
        "page_end": 4,
        "pages_with_boxes": [3],
        "chunk_type": "text",
    }


def test_the_index_is_asked_for_the_document_and_the_chunk_together(as_viewer, chunked, passage):
    """Both ids go to the index, so one document's URL cannot read another's passage."""
    as_viewer.get(url())

    assert passage == [(TABLE, str(ASSET_ID), CHUNK_ID)]


def test_a_passage_with_no_page_recorded_still_reads(as_viewer, chunked, monkeypatch):
    monkeypatch.setattr(
        chunks,
        "chunk",
        lambda *args: {"chunk_id": CHUNK_ID, "text": "Plain text.", "bboxes": [], "score": None},
    )

    body = as_viewer.get(url()).json()

    assert body["page_start"] is None
    assert body["page_end"] is None
    assert body["pages_with_boxes"] == []
    assert body["heading_path"] == []
    assert body["chunk_type"] == "text"


def test_an_unknown_document_is_a_404_and_the_index_is_not_asked(as_viewer, passage, monkeypatch):
    monkeypatch.setattr(kb, "document_chunks_uri", lambda asset_id: None)

    assert as_viewer.get(url()).status_code == 404
    assert passage == []


def test_a_passage_the_document_does_not_have_is_a_404(as_viewer, chunked, passage):
    assert as_viewer.get(url("ffff")).status_code == 404


@pytest.mark.parametrize(
    "chunk_id",
    ["o'brien", "a b", "x" * 129, ".", "..", "..."],
    ids=["quote", "space", "long", "dot", "two dots", "three dots"],
)
def test_a_chunk_id_that_is_not_one_is_refused_before_any_read(
    as_viewer, chunked, passage, chunk_id
):
    response = as_viewer.get(url(chunk_id))

    assert response.status_code == 400
    assert passage == []


def test_an_unreachable_index_is_a_503(as_viewer, chunked, monkeypatch):
    def down(*args):
        raise chunks.ChunkStoreUnavailable("OSError")

    monkeypatch.setattr(chunks, "chunk", down)

    assert as_viewer.get(url()).status_code == 503


def test_a_failing_index_is_a_502(as_viewer, chunked, monkeypatch):
    def broken(*args):
        raise chunks.ChunkStoreError("RuntimeError")

    monkeypatch.setattr(chunks, "chunk", broken)

    assert as_viewer.get(url()).status_code == 502


def test_an_api_key_may_read_it(api, db, chunked, passage):
    """The Ask agent calls with an API key, which may only read (docs/adr/021)."""
    from django.contrib.auth.models import User

    from apps.accounts.models import ApiKey, Role, UserProfile

    user = User.objects.create_user(username="gobase-agent")
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    _, key = ApiKey.issue(user, "test")
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")

    assert api.get(url()).status_code == 200


def test_an_asset_id_that_is_not_a_uuid_is_a_404(as_viewer, chunked, passage):
    assert as_viewer.get(f"/api/catalog/assets/not-a-uuid/passages/{CHUNK_ID}").status_code == 404
    assert passage == []


# The index for real: a local Lance table where the catalog points, as
# `test_chunk_store.py` builds one. Only the catalog lookup is faked.

OTHER_ASSET_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")


@pytest.fixture
def real_index(tmp_path, monkeypatch):
    import lancedb

    name = "BAAI_bge-small-en-v1.5"
    rows = [
        {
            "chunk_id": CHUNK_ID,
            "asset_id": str(ASSET_ID),
            "doc_id": "sha-1",
            "ord": 0,
            "text": "Screening at the checkpoint.",
            "token_count": 5,
            "chunk_type": "text",
            "heading_path": ["3 Security"],
            "page_start": 2,
            "page_end": 2,
            "bboxes": '[{"page": 2, "bbox": [100, 200, 900, 260]}]',
            "vector": [1.0, 0.0, 0.0],
        }
    ]
    lancedb.connect(str(tmp_path)).create_table(name, data=rows)
    chunks.reset()
    monkeypatch.setattr(kb, "document_chunks_uri", lambda asset_id: f"{tmp_path}/{name}.lance")
    yield tmp_path
    chunks.reset()


def test_a_passage_is_read_from_a_real_table(as_viewer, real_index):
    body = as_viewer.get(url()).json()

    assert body["text"] == "Screening at the checkpoint."
    assert (body["page_start"], body["page_end"], body["pages_with_boxes"]) == (3, 3, [3])


def test_another_documents_url_cannot_read_the_passage(as_viewer, real_index):
    """The chunk id is real; the document in the URL is not the one it belongs to."""
    response = as_viewer.get(f"/api/catalog/assets/{OTHER_ASSET_ID}/passages/{CHUNK_ID}")

    assert response.status_code == 404


def test_a_table_the_bucket_does_not_hold_is_a_404(as_viewer, real_index, monkeypatch):
    """The catalog names a table the data platform has not written yet."""
    monkeypatch.setattr(
        kb, "document_chunks_uri", lambda asset_id: f"{real_index}/another-model.lance"
    )

    assert as_viewer.get(url()).status_code == 404
