"""GET /api/catalog/assets/{id}/pages/{page}.png — a page with a passage marked.

The catalog is faked at its own boundary and the chunk index at `chunks.chunk`,
since tests have no real `kb` or bucket. The lake and the renderer are not: the
200 reads a real PDF from a temporary directory through DuckDB and renders it
with pdfium, exactly as the deployed path does with an object in bronze.
"""

import io
import uuid

import pypdfium2 as pdfium
import pytest
from PIL import Image

from apps.catalog import chunks, kb, pages
from apps.map import lake

ASSET_ID = uuid.UUID("b9bb3097-9feb-4805-b4b3-aed8d25fbada")
TABLE = "s3://geobase-silver/index/chunks/BAAI_bge-small-en-v1.5.lance"
HASH = "0e2c" * 16


def url(page, chunk=None):
    base = f"/api/catalog/assets/{ASSET_ID}/pages/{page}.png"
    return f"{base}?chunk={chunk}" if chunk else base


@pytest.fixture
def pdf_on_disk(tmp_path, monkeypatch):
    """A real two-page PDF where the catalog says the document's PDF is."""
    document = pdfium.PdfDocument.new()
    document.new_page(200, 100)
    document.new_page(200, 100)
    path = tmp_path / "Beirut airport - Case Study - TiSO.pdf"
    out = io.BytesIO()
    document.save(out)
    path.write_bytes(out.getvalue())
    monkeypatch.setattr(
        kb,
        "document_pdf",
        lambda asset_id: {
            "pdf_uri": str(path),
            "content_hash": HASH,
            "filename": path.name,
            "pages": 2,
            "chunks_uri": TABLE,
        },
    )
    return path


@pytest.fixture
def passage(monkeypatch):
    """One passage in the index: the left half of page 2 (page 1 to the index)."""
    asked = []

    def fake(chunks_uri, asset_id, chunk_id):
        asked.append((chunks_uri, str(asset_id), chunk_id))
        if chunk_id != "0a1b":
            return None
        return {
            "chunk_id": "0a1b",
            "asset_id": str(asset_id),
            "bboxes": [{"page": 1, "bbox": [0, 0, 500, 1000]}, {"page": 0, "bbox": [0, 0, 10, 10]}],
        }

    monkeypatch.setattr(chunks, "chunk", fake)
    return asked


@pytest.fixture(autouse=True)
def _fresh_connections():
    lake.reset()
    chunks.reset()
    yield
    lake.reset()
    chunks.reset()


def _pixel(content: bytes, x_fraction: float):
    image = Image.open(io.BytesIO(content)).convert("RGB")
    width, height = image.size
    return image.getpixel((int(width * x_fraction), height // 2))


def test_requires_authentication(api):
    assert api.get(url(2)).status_code == 401


def test_renders_the_page_with_the_passage_drawn_on_it(as_viewer, pdf_on_disk, passage):
    response = as_viewer.get(url(2, "0a1b"))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["Content-Length"] == str(len(response.content))
    assert passage == [(TABLE, str(ASSET_ID), "0a1b")]
    # Page 2 to a reader is page 1 to the index: only that page's box is drawn,
    # on the left half.
    assert _pixel(response.content, 0.25) != (255, 255, 255)
    assert _pixel(response.content, 0.75) == (255, 255, 255)


def test_without_a_chunk_the_plain_page_is_rendered_and_the_index_not_asked(
    as_viewer, pdf_on_disk, passage
):
    response = as_viewer.get(url(2))

    assert response.status_code == 200
    assert passage == []
    assert _pixel(response.content, 0.25) == (255, 255, 255)


def test_the_etag_names_the_pdf_the_passage_the_page_and_the_renderer(
    as_viewer, pdf_on_disk, passage
):
    response = as_viewer.get(url(2, "0a1b"))

    assert response["ETag"] == f'"{HASH}:0a1b:2:r{pages.RENDER_VERSION}"'
    assert response["Cache-Control"] == "private, no-cache"
    assert as_viewer.get(url(2))["ETag"] == f'"{HASH}:-:2:r{pages.RENDER_VERSION}"'


def test_a_matching_etag_reads_neither_the_lake_nor_the_index(as_viewer, pdf_on_disk, monkeypatch):
    def refuse(*args):
        raise AssertionError("a revalidation must cost a catalog lookup only")

    monkeypatch.setattr(lake, "read_blob", refuse)
    monkeypatch.setattr(chunks, "chunk", refuse)

    response = as_viewer.get(
        url(2, "0a1b"), HTTP_IF_NONE_MATCH=f'"{HASH}:0a1b:2:r{pages.RENDER_VERSION}"'
    )

    assert response.status_code == 304


@pytest.mark.parametrize("page", [0, 3], ids=["page zero", "past the end"])
def test_a_page_the_document_does_not_have_is_a_404(as_viewer, pdf_on_disk, passage, page):
    assert as_viewer.get(url(page, "0a1b")).status_code == 404


def test_an_unknown_document_is_a_404(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "document_pdf", lambda asset_id: None)
    assert as_viewer.get(url(1)).status_code == 404


def test_a_passage_the_document_does_not_have_is_a_404(as_viewer, pdf_on_disk, passage):
    assert as_viewer.get(url(2, "ffff")).status_code == 404


def test_a_document_without_a_chunk_table_has_no_passage_to_draw(as_viewer, tmp_path, monkeypatch):
    monkeypatch.setattr(
        kb,
        "document_pdf",
        lambda asset_id: {
            "pdf_uri": str(tmp_path / "x.pdf"),
            "content_hash": HASH,
            "filename": "x.pdf",
            "pages": 2,
            "chunks_uri": None,
        },
    )

    assert as_viewer.get(url(1, "0a1b")).status_code == 404


@pytest.mark.parametrize("chunk", ["a b", "a'b", "x" * 129], ids=["space", "quote", "too long"])
def test_a_chunk_id_that_is_not_one_is_refused_before_anything_is_read(
    as_viewer, pdf_on_disk, passage, chunk
):
    assert as_viewer.get(url(2, chunk)).status_code == 400
    assert passage == []


def test_an_unreachable_index_is_a_503(as_viewer, pdf_on_disk, monkeypatch):
    def down(*args):
        raise chunks.ChunkStoreUnavailable("OSError")

    monkeypatch.setattr(chunks, "chunk", down)

    assert as_viewer.get(url(2, "0a1b")).status_code == 503


def test_a_failed_index_read_is_a_502(as_viewer, pdf_on_disk, monkeypatch):
    def failed(*args):
        raise chunks.ChunkStoreError("ValueError")

    monkeypatch.setattr(chunks, "chunk", failed)

    assert as_viewer.get(url(2, "0a1b")).status_code == 502


def test_a_pdf_the_lake_no_longer_holds_is_a_502(as_viewer, tmp_path, passage, monkeypatch):
    monkeypatch.setattr(
        kb,
        "document_pdf",
        lambda asset_id: {
            "pdf_uri": str(tmp_path / "moved-away.pdf"),
            "content_hash": HASH,
            "filename": "moved-away.pdf",
            "pages": 2,
            "chunks_uri": TABLE,
        },
    )

    assert as_viewer.get(url(2, "0a1b")).status_code == 502


def test_an_unreachable_lake_is_a_503(as_viewer, pdf_on_disk, passage, monkeypatch):
    def unreachable(uri):
        raise lake.LakeUnavailable("connection refused")

    monkeypatch.setattr(lake, "read_blob", unreachable)

    assert as_viewer.get(url(2, "0a1b")).status_code == 503


def test_bytes_that_are_not_a_pdf_are_a_502(as_viewer, tmp_path, passage, monkeypatch):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    monkeypatch.setattr(
        kb,
        "document_pdf",
        lambda asset_id: {
            "pdf_uri": str(path),
            "content_hash": HASH,
            "filename": path.name,
            "pages": 2,
            "chunks_uri": TABLE,
        },
    )

    assert as_viewer.get(url(1)).status_code == 502
