"""The only module that renders a PDF page.

A passage found in the chunk index knows which page it is on and where on the
page, as boxes on MinerU's 0..1000 grid (context/integrations/lance.md). This
turns one page of the PDF into an image with those boxes drawn on it, so the
match can be seen rather than searched for (docs/adr/020). The pattern is the
data platform's own demo, `godoc/demo/gobase_demo_server.py`.

Bytes in, bytes out: the PDF is read from bronze by the lake module and
nothing here knows where it came from.
"""

import io
import threading

import pypdfium2 as pdfium
from PIL import ImageDraw

# Rendered pixels per PDF point. 1.6 keeps body text readable at the width a
# card offers without a page costing a megabyte.
RENDER_SCALE = 1.6

# Goes into the page endpoint's ETag, so a change to how a page is drawn
# invalidates the copies browsers hold.
RENDER_VERSION = "1"

# The side of the grid the boxes are on.
GRID = 1000

# The highlight. The brand emerald (`--primary` in dark mode, #12b085): a
# design token cannot reach an image drawn on the server, so its value is
# written here and context/ui-registry.md says so. Fill is faint, stroke solid.
HIGHLIGHT_FILL = (18, 176, 133, 40)
HIGHLIGHT_STROKE = (18, 176, 133, 255)
HIGHLIGHT_WIDTH = 3

# pdfium is not thread-safe, and sync views run on a thread pool under uvicorn.
_lock = threading.Lock()


class PageUnreadable(Exception):
    """The bytes are not a PDF, or the page is not in it."""


def render(pdf: bytes, page_index: int, boxes) -> bytes:
    """Page `page_index` (from 0) of `pdf` as PNG bytes, with `boxes` drawn on it.

    Each box is `[x0, y0, x1, y1]` on the 0..1000 grid, already filtered to
    this page by the caller. No boxes draws the plain page.
    """
    with _lock:
        try:
            document = pdfium.PdfDocument(pdf)
        except pdfium.PdfiumError as exc:
            raise PageUnreadable(type(exc).__name__) from exc
        try:
            if not 0 <= page_index < len(document):
                raise PageUnreadable("No such page")
            page = document[page_index]
            image = page.render(scale=RENDER_SCALE).to_pil().convert("RGB")
        except pdfium.PdfiumError as exc:
            raise PageUnreadable(type(exc).__name__) from exc
        finally:
            document.close()

    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    for x0, y0, x1, y1 in boxes:
        draw.rectangle(
            (x0 * width / GRID, y0 * height / GRID, x1 * width / GRID, y1 * height / GRID),
            fill=HIGHLIGHT_FILL,
            outline=HIGHLIGHT_STROKE,
            width=HIGHLIGHT_WIDTH,
        )

    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
