"""The page renderer, run against a real PDF built in memory."""

import io

import pypdfium2 as pdfium
import pytest
from PIL import Image

from apps.catalog import pages

WIDTH, HEIGHT = 200, 100


@pytest.fixture
def pdf() -> bytes:
    """A one-page blank PDF, 200 by 100 points."""
    document = pdfium.PdfDocument.new()
    document.new_page(WIDTH, HEIGHT)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _image(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_renders_the_page_as_png_at_the_render_scale(pdf):
    png = pages.render(pdf, 0, [])

    assert png.startswith(b"\x89PNG")
    assert _image(png).size == (
        round(WIDTH * pages.RENDER_SCALE),
        round(HEIGHT * pages.RENDER_SCALE),
    )


def test_a_box_is_drawn_where_the_grid_says(pdf):
    # The left half of the page, top to bottom, on the 0..1000 grid.
    png = pages.render(pdf, 0, [[0, 0, 500, 1000]])
    image = _image(png)
    width, height = image.size

    inside = image.getpixel((width // 4, height // 2))
    outside = image.getpixel((3 * width // 4, height // 2))

    assert outside == (255, 255, 255)
    assert inside != outside
    # Tinted, not painted over: the page shows through the fill.
    assert all(channel > 128 for channel in inside)


def test_no_boxes_leaves_the_page_untouched(pdf):
    image = _image(pages.render(pdf, 0, []))

    assert image.getpixel((10, 10)) == (255, 255, 255)


def test_a_page_the_document_does_not_have_is_unreadable(pdf):
    with pytest.raises(pages.PageUnreadable):
        pages.render(pdf, 1, [])


def test_bytes_that_are_not_a_pdf_are_unreadable():
    with pytest.raises(pages.PageUnreadable):
        pages.render(b"not a pdf", 0, [])
