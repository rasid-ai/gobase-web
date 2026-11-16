"""Deep search: the two steps joined, and the shape that comes out.

Both stores are faked at their own boundaries — the catalog at
`kb.chunked_documents`, the chunk index at `chunks.search` — so what is under
test is the joining: which documents are searched where, how passages fold into
documents, how documents rank, and that pages are counted from 1 on the way out.
"""

import pytest

from apps.catalog import chunks, kb, passages

VECTOR = [0.1, 0.2, 0.3]
MODEL = "BAAI/bge-small-en-v1.5"
TABLE = "s3://geobase-silver/index/chunks/BAAI_bge-small-en-v1.5.lance"


def document(asset_id, **overrides):
    return {
        "asset_id": asset_id,
        "name": f"{asset_id}.pdf",
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
        "document": {"title": None, "pages": 8, "pdf": True},
        "chunks_uri": TABLE,
        **overrides,
    }


def hit(asset_id, chunk_id, score, **overrides):
    return {
        "chunk_id": chunk_id,
        "asset_id": asset_id,
        "doc_id": "sha",
        "ord": 0,
        "text": f"passage {chunk_id}",
        "token_count": 2,
        "chunk_type": "text",
        "heading_path": ["3 Security"],
        "page_start": 2,
        "page_end": 3,
        "bboxes": [{"page": 2, "bbox": [0, 0, 10, 10]}, {"page": 3, "bbox": [0, 0, 10, 10]}],
        "score": score,
        **overrides,
    }


@pytest.fixture
def catalog(monkeypatch):
    """Answers with the documents in scope, and records what was asked."""
    asked = {}
    found = [document("doc-1"), document("doc-2")]

    def fake(**kwargs):
        asked.update(kwargs)
        return found

    monkeypatch.setattr(kb, "chunked_documents", fake)
    asked["found"] = found
    return asked


@pytest.fixture
def index(monkeypatch):
    """Answers with passages, and records each table search."""
    calls = []
    answers = {
        TABLE: [
            hit("doc-2", "x", 0.9),
            hit("doc-1", "a", 0.8),
            hit("doc-1", "b", 0.7),
            hit("doc-1", "c", 0.6),
            hit("doc-2", "y", 0.5),
        ]
    }

    def fake(chunks_uri, vector, asset_ids, k):
        calls.append(
            {"chunks_uri": chunks_uri, "vector": vector, "asset_ids": list(asset_ids), "k": k}
        )
        # Honours the prefilter, as the index does.
        return [hit for hit in answers.get(chunks_uri, []) if hit["asset_id"] in asset_ids]

    monkeypatch.setattr(chunks, "search", fake)
    return calls


def test_the_scope_reaches_the_catalog_and_the_shortlist_reaches_the_index(catalog, index):
    passages.search(
        VECTOR,
        MODEL,
        limit=10,
        per_document=3,
        dataset="airports",
        bbox=[35.4, 33.8, 35.6, 34.1],
        coverage="dataset",
        ingested_after="A",
    )

    assert catalog["embedder_id"] == MODEL
    assert catalog["dataset"] == "airports"
    assert catalog["bbox"] == [35.4, 33.8, 35.6, 34.1]
    assert catalog["coverage"] == "dataset"
    assert catalog["ingested_after"] == "A"
    (call,) = index
    assert call == {"chunks_uri": TABLE, "vector": VECTOR, "asset_ids": ["doc-1", "doc-2"], "k": 30}


def test_passages_fold_into_their_document_ranked_by_the_best(catalog, index):
    results = passages.search(VECTOR, MODEL, limit=10, per_document=3)

    assert [result["asset_id"] for result in results] == ["doc-2", "doc-1"]
    assert results[0]["score"] == 0.9
    assert [passage["chunk_id"] for passage in results[0]["passages"]] == ["x", "y"]
    assert [passage["chunk_id"] for passage in results[1]["passages"]] == ["a", "b", "c"]


def test_per_document_caps_the_passages_and_limit_the_documents(catalog, index):
    results = passages.search(VECTOR, MODEL, limit=1, per_document=2)

    assert [result["asset_id"] for result in results] == ["doc-2"]
    assert [passage["chunk_id"] for passage in results[0]["passages"]] == ["x", "y"]


def test_pages_are_counted_from_one_on_the_way_out(catalog, index):
    (first, _) = passages.search(VECTOR, MODEL, limit=10, per_document=3)
    passage = first["passages"][0]

    # The index stores 2–3; a reader, a PDF viewer and the page endpoint say 3–4.
    assert passage["page_start"] == 3
    assert passage["page_end"] == 4
    assert passage["pages_with_boxes"] == [3, 4]


def test_a_passage_carries_what_the_card_shows_and_nothing_else(catalog, index):
    (first, _) = passages.search(VECTOR, MODEL, limit=10, per_document=3)

    assert first["passages"][0] == {
        "chunk_id": "x",
        "text": "passage x",
        "heading_path": ["3 Security"],
        "page_start": 3,
        "page_end": 4,
        "pages_with_boxes": [3, 4],
        "chunk_type": "text",
        "score": 0.9,
    }
    assert "chunks_uri" not in first


def test_a_passage_with_no_page_stays_pageless(catalog, monkeypatch):
    monkeypatch.setattr(
        chunks,
        "search",
        lambda *a, **k: [hit("doc-1", "p", 0.5, page_start=None, page_end=None, bboxes=[])],
    )

    (result,) = passages.search(VECTOR, MODEL, limit=10, per_document=3)

    assert result["passages"][0]["page_start"] is None
    assert result["passages"][0]["pages_with_boxes"] == []


def test_a_passage_of_a_document_out_of_scope_is_skipped(catalog, monkeypatch):
    # The table can hold rows of a catalog that no longer exists; the
    # prefilter keeps them out, and if one slips through it is nobody's answer.
    monkeypatch.setattr(
        chunks, "search", lambda *a, **k: [hit("doc-9", "z", 0.99), hit("doc-1", "a", 0.8)]
    )

    results = passages.search(VECTOR, MODEL, limit=10, per_document=3)

    assert [result["asset_id"] for result in results] == ["doc-1"]


def test_no_documents_in_scope_searches_nothing(monkeypatch, index):
    monkeypatch.setattr(kb, "chunked_documents", lambda **kwargs: [])

    assert passages.search(VECTOR, MODEL, limit=10, per_document=3) == []
    assert index == []


def test_documents_in_two_tables_are_searched_table_by_table(monkeypatch, index):
    other = "s3://other-silver/index/chunks/BAAI_bge-small-en-v1.5.lance"
    monkeypatch.setattr(
        kb,
        "chunked_documents",
        lambda **kwargs: [document("doc-1"), document("doc-3", chunks_uri=other)],
    )

    passages.search(VECTOR, MODEL, limit=10, per_document=3)

    assert [(call["chunks_uri"], call["asset_ids"]) for call in index] == [
        (TABLE, ["doc-1"]),
        (other, ["doc-3"]),
    ]


def test_document_ids_narrow_the_shortlist_within_the_scope(catalog, index):
    passages.search(VECTOR, MODEL, limit=10, per_document=3, asset_ids=["doc-2", "doc-9"])

    # doc-9 is not in scope, so asking for it does not let it in.
    (call,) = index
    assert call["asset_ids"] == ["doc-2"]


def test_document_ids_outside_the_scope_search_nothing(catalog, index):
    assert passages.search(VECTOR, MODEL, limit=10, per_document=3, asset_ids=["doc-9"]) == []
    assert index == []
