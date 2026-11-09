"""GET /api/catalog/assets/{id}/pdf — a document's PDF, read from bronze.

The catalog is faked at its own boundary because tests have no real `kb`
(context/integrations/kb.md). The lake is not: the 200 reads a real file from a
temporary directory, which DuckDB reads from a local path exactly as it reads
one from S3. The two failure codes are faked at the lake boundary instead,
since a dead object store is not something a test should need.
"""

import uuid

import pytest

from apps.catalog import kb
from apps.map import lake

ASSET_ID = uuid.UUID("b9bb3097-9feb-4805-b4b3-aed8d25fbada")
URL = f"/api/catalog/assets/{ASSET_ID}/pdf"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj << >> endobj\n%%EOF\n"


@pytest.fixture
def pdf_on_disk(tmp_path, monkeypatch):
    """A real PDF file where the catalog says the document's PDF is."""
    path = tmp_path / "Beirut airport - Case Study - TiSO.pdf"
    path.write_bytes(PDF)
    monkeypatch.setattr(
        kb,
        "document_pdf",
        lambda asset_id: {
            "pdf_uri": str(path),
            "content_hash": "0e2c" * 16,
            "filename": path.name,
        },
    )
    return path


@pytest.fixture(autouse=True)
def _fresh_lake_connection():
    lake.reset()
    yield
    lake.reset()


def test_requires_authentication(api):
    assert api.get(URL).status_code == 401


def test_serves_the_pdf_inline_under_its_own_name(as_viewer, pdf_on_disk):
    response = as_viewer.get(URL)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content == PDF
    assert response["Content-Length"] == str(len(PDF))
    # Inline, so the browser's viewer opens it; named, so a save keeps the name.
    assert (
        response["Content-Disposition"]
        == 'inline; filename="Beirut airport - Case Study - TiSO.pdf"'
    )


def test_the_etag_is_the_pdfs_own_hash(as_viewer, pdf_on_disk):
    """`content_hash` is the PDF's sha256, so the tag is strong and costs no read."""
    response = as_viewer.get(URL)

    assert response["ETag"] == '"' + "0e2c" * 16 + '"'
    assert response["Cache-Control"] == "private, no-cache"


def test_a_matching_etag_is_answered_without_reading_the_lake(as_viewer, pdf_on_disk, monkeypatch):
    def refuse(uri):
        raise AssertionError("the lake must not be read for a revalidation")

    monkeypatch.setattr(lake, "read_blob", refuse)

    response = as_viewer.get(URL, HTTP_IF_NONE_MATCH='"' + "0e2c" * 16 + '"')

    assert response.status_code == 304
    assert response["ETag"] == '"' + "0e2c" * 16 + '"'


def test_a_stale_etag_gets_the_pdf_again(as_viewer, pdf_on_disk):
    response = as_viewer.get(URL, HTTP_IF_NONE_MATCH='"something-else"')

    assert response.status_code == 200
    assert response.content == PDF


def test_an_unknown_asset_is_a_404(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "document_pdf", lambda asset_id: None)
    assert as_viewer.get(URL).status_code == 404


def test_a_revalidation_of_a_vanished_document_is_a_404_not_a_304(as_viewer, monkeypatch):
    """A superseded document must not tell the browser its old copy is still good."""
    monkeypatch.setattr(kb, "document_pdf", lambda asset_id: None)

    response = as_viewer.get(URL, HTTP_IF_NONE_MATCH="*")

    assert response.status_code == 404


def test_a_pdf_the_lake_no_longer_holds_is_a_502(as_viewer, tmp_path, monkeypatch):
    """The catalog's path can go stale after a move in bronze (docs/adr/027)."""
    monkeypatch.setattr(
        kb,
        "document_pdf",
        lambda asset_id: {
            "pdf_uri": str(tmp_path / "moved-away.pdf"),
            "content_hash": "abc",
            "filename": "moved-away.pdf",
        },
    )

    assert as_viewer.get(URL).status_code == 502


def test_an_unreachable_lake_is_a_503(as_viewer, pdf_on_disk, monkeypatch):
    def unreachable(uri):
        raise lake.LakeUnavailable("connection refused")

    monkeypatch.setattr(lake, "read_blob", unreachable)

    assert as_viewer.get(URL).status_code == 503
