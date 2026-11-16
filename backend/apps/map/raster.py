"""The only module that reads a raster's pixels.

The catalog's rasters are COGs (Cloud-Optimized GeoTIFFs: rasters laid out so
a reader can fetch just the part it needs) in the lake. This module answers
two questions about one of them, for the Ask agent's `raster_clip` tool
(docs/adr/024, docs/adr/029): what the pixels inside a place say, as figures,
and the pixels over a place themselves, as a small GeoTIFF.

It reads only the window over the place, and never more pixels than a budget
the caller sets. Desktop clients still read whole COGs themselves, with
credentials from `sts.py` (docs/adr/022); nothing here serves them.

`rasterio` (GDAL) is imported on first use, not at import: the wheel is large,
and neither start-up nor a test that never reads a raster should pay for it.
It reads with the lake's read-only settings, the ones DuckDB uses
(context/integrations/raster.md), and never writes to the lake.
"""

import contextlib
import json
import logging
import math
import os
import re
import tempfile
import time

from django.conf import settings

logger = logging.getLogger(__name__)


class RasterUnavailable(Exception):
    """The lake could not be reached: refused, unresolved, or not authorised."""


class RasterReadError(Exception):
    """The lake answered, but the object is missing or not readable as a raster."""


class RasterNotPlaceable(Exception):
    """A place cannot be put on this raster: its extent has no lon/lat box.

    Not the lake's fault and not a broken file: the raster's layout is one
    this reader does not support (context/integrations/raster.md, "Known
    limits"). Its own exception so the answer can say so. With no place the
    raster still reads whole.
    """


class NoOverlap(Exception):
    """The place does not touch the raster."""


class ClipNotWritten(Exception):
    """The clip could not be written to this server's own disk.

    Not the lake's fault and not the caller's: the temporary folder is full
    or cannot be written. Its own exception so it is never reported as a bad
    raster.
    """


class ClipTooLarge(Exception):
    """The window over the place holds more bytes of pixels than a clip may.

    `size` and `allowed` are bytes before compression: width x height x bands
    x bytes per value. `pixels` is width x height, for the message.
    """

    def __init__(self, size: int, allowed: int, pixels: int) -> None:
        super().__init__(f"{size} bytes, {allowed} allowed")
        self.size = size
        self.allowed = allowed
        self.pixels = pixels


# Substrings that mark a failure as "could not reach the lake" rather than
# "could not read the file", as in lake.py. GDAL reports both as one error
# type, so the message is all there is to go on. The message itself is never
# logged or passed on: it can quote the object's path.
_UNAVAILABLE_MARKERS = (
    "could not resolve",
    "couldn't resolve",
    "couldn't connect",
    "could not connect",
    "failed to connect",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "http response code: 401",
    "http response code: 403",
    "access denied",
    "accessdenied",
    "invalidaccesskeyid",
    "access key id you provided",
    "signaturedoesnotmatch",
    "curl error",
    "operation too slow",
    # The lake answering that it cannot serve right now, or a proxy in front
    # of it doing so. GDAL passes on the lake's sentence, not its error code,
    # so these are the sentences AWS, MinIO and RustFS use (checked against a
    # local socket answering each one, 2026-11-10).
    "unable to handle request",
    "serviceunavailable",
    "reduce your request rate",
    "slowdown",
    "slow down",
    "encountered an internal error",
    "internalerror",
    "invalid aws response",
    # Credentials that stopped working, or a clock that drifted: the same
    # kind of failure as a refused key, which is already "unavailable".
    "token has expired",
    "expiredtoken",
    "difference between the request time",
    "requesttimetooskewed",
)

# A session that found no credentials, or was refused: the lake was not read.
_UNAVAILABLE_TYPES = frozenset(
    {"NoCredentialsError", "PartialCredentialsError", "EndpointConnectionError", "ClientError"}
)

# How many points each edge of a place is cut into before it is moved into the
# raster's CRS. A straight edge in lon/lat is a curve in a projected CRS; with
# the corners alone it would be cut short.
_EDGE_POINTS = 16

# How close to a pixel edge, in pixels, counts as on it (see `_span`).
_PIXEL_EDGE = 1e-6

# How long the lake may take, in seconds. GDAL takes these per request, and
# makes up to three requests to open one raster (two for its header, one to
# ask whether the path is a folder), so opening a dead lake costs up to three
# times a figure (context/integrations/raster.md has each case, measured).
# To connect:
_CONNECT_SECONDS = 5
# A request that receives fewer than `_STALL_BYTES` a second for this long is
# given up on. This is what ends a lake that connects and then says nothing.
_STALL_SECONDS = 8
_STALL_BYTES = 1024
# One request, however well it is going. The largest one a read makes is about
# 8 MB, so this asks for a link of 0.6 Mbit/s or better (ADR-030).
_REQUEST_SECONDS = 120
# A whole read, from open to last pixel, when the caller names no limit
# (`RASTER_READ_TIMEOUT_SECONDS`). Checked between steps, so a read can run
# over by one step: one chunk of a statistics read, one strip of a clip. Zero
# or less means no limit of this kind; GDAL's bounds on each request stay.
READ_SECONDS = 300

# How much a statistics read asks of the lake in one step, and holds from it.
# A step is one chunk of rows, all bands at once. `_CHUNK_BLOCK_BYTES` is the
# size, before compression, of the blocks (tiles) a chunk touches: a block is
# fetched whole, so this, not the window's width, is what a chunk pulls. It
# keeps a step to a few seconds on a modest link, so the time limit above is
# looked at that often. `_CHUNK_HELD_BYTES` caps the pixels a chunk holds in
# memory, for a window many blocks wide.
_CHUNK_BLOCK_BYTES = 4 * 1024 * 1024
_CHUNK_HELD_BYTES = 16 * 1024 * 1024

# The most distinct values reported as classes. A legend has a handful. The
# rest are summed into `other_classes`, so the shares still add up to 1.
MAX_CLASSES = 256

# How many bytes of pixels a clip moves from the source to the file at a time.
# Whole blocks of rows, so the clip never holds every band at full size twice.
_STRIP_BYTES = 8 * 1024 * 1024
_BLOCK = 256

# GDAL's block cache, in bytes (rasterio takes this one option as a number).
_GDAL_CACHE_BYTES = 32 * 1024 * 1024

_RING = re.compile(r"^\s*POLYGON\s*\(\(\s*([^()]*?)\s*\)\)\s*$", re.IGNORECASE)

# The tags a clip carries, by name. A list of what is wanted, not a guess at
# what is unsafe: a tag can hold a path in more shapes than a pattern can
# name (a URL to the lake, a relative path, `src=/home/...`), and the lake's
# layout is not the client's to know. These are the tags the data platform
# writes on a raster, plus the descriptive TIFF fields.
_DATASET_TAGS = frozenset(
    {
        "classes",
        "collection",
        "description",
        "source",
        "year",
        "AREA_OR_POINT",
        "TIFFTAG_COPYRIGHT",
        "TIFFTAG_DATETIME",
        "TIFFTAG_IMAGEDESCRIPTION",
        "TIFFTAG_RESOLUTIONUNIT",
        "TIFFTAG_XRESOLUTION",
        "TIFFTAG_YRESOLUTION",
    }
)
# The tags on the list that hold a sentence. A sentence may hold a slash
# ("Land Use/Land Cover"), so these are checked for the shape of a path
# (`_names_a_path`). Every other tag on the list is a short value — a year, a
# collection id, a provider's name — and is dropped if it holds a slash or a
# backslash at all.
_PROSE_TAGS = frozenset({"description", "TIFFTAG_COPYRIGHT", "TIFFTAG_IMAGEDESCRIPTION"})
# Band tags are GDAL's own figures for the band; nothing else is carried.
_BAND_TAG_PREFIX = "STATISTICS_"

# A legend's key: a class value, which is a whole number.
_WHOLE_NUMBER = re.compile(r"^-?\d{1,20}$")

# The end of a file's name: a dot and a short extension.
_FILE_END = re.compile(r"\.[A-Za-z0-9]{2,7}$")


# Pointers into some other GDAL or PROJ installation. Conda exports them
# shell-wide; the rasterio wheel bundles its own data, and an inherited
# `PROJ_DATA` from an older PROJ fails every CRS lookup. The data platform
# drops the same four (`gobase_orchestration/lib/transforms.py`).
_STALE_GDAL_VARS = ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA", "GDAL_DRIVER_PATH")


def _rasterio():
    """`rasterio`, imported on first use, with nothing inherited to mislead it.

    The four variables are dropped from this process before the import: no
    other module here uses GDAL, and a variable the operator never chose must
    not break a correct read.
    """
    for name in _STALE_GDAL_VARS:
        os.environ.pop(name, None)
    import rasterio

    _silence(logging.getLogger("rasterio"))
    return rasterio


def _silence(rasterio_logger: logging.Logger) -> None:
    """Keep rasterio's own log lines out of every log.

    rasterio logs every GDAL error on `rasterio._env`, and a GDAL error about
    an object in the lake quotes its URL: endpoint, bucket and key. So the
    `rasterio` logger and everything under it is switched off: a level no
    record reaches, which its child loggers inherit, and no passing on to the
    root logger in case one of them is given a level of its own. What failed
    is still logged, by exception type, in `_classify`.
    """
    rasterio_logger.setLevel(logging.CRITICAL + 1)
    rasterio_logger.propagate = False
    if not rasterio_logger.handlers:
        rasterio_logger.addHandler(logging.NullHandler())


def _options() -> dict[str, str | int]:
    """GDAL's configuration for the configured object store, without credentials.

    The same settings DuckDB reads the lake with (context/integrations/lake.md).
    A custom endpoint is RustFS or MinIO; a blank one is AWS's own, which needs
    none of this.

    The timeouts bound how long a dead lake holds a worker: `_CONNECT_SECONDS`
    to connect, `_STALL_SECONDS` of near silence on a request that connected,
    `_REQUEST_SECONDS` for any one request, and no retry. GDAL waits thirty
    seconds before a retry by default, which turned one retry against a lake
    that drops packets into 85 seconds; and without the silence rule a lake
    that connected and then said nothing held a worker for three whole
    requests, 90 seconds (context/integrations/raster.md).
    """
    options = {
        # Without this GDAL lists the object's folder on every open, looking
        # for side files. A COG has none.
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_CONNECTTIMEOUT": str(_CONNECT_SECONDS),
        "GDAL_HTTP_TIMEOUT": str(_REQUEST_SECONDS),
        "GDAL_HTTP_LOW_SPEED_TIME": str(_STALL_SECONDS),
        "GDAL_HTTP_LOW_SPEED_LIMIT": str(_STALL_BYTES),
        "GDAL_HTTP_MAX_RETRY": "0",
        # A clip of a raster with a mask keeps it inside the file. GDAL's
        # default is a side file, which is not part of the clip handed back.
        "GDAL_TIFF_INTERNAL_MASK": "YES",
        # GDAL keeps the blocks it has read or is about to write in a cache of
        # its own, 5% of the machine's memory by default. Bounded, so what a
        # read holds is this module's budgets and not the size of the host.
        "GDAL_CACHEMAX": _GDAL_CACHE_BYTES,
        # GDAL also remembers an object in the lake after the file is closed:
        # its size, its header, parts of it. A later read would then be
        # answered from that memory, even after the object was replaced or
        # the credentials stopped working. Nothing under /vsis3/ is kept.
        "CPL_VSIL_CURL_NON_CACHED": "/vsis3/",
    }
    if settings.LAKE_S3_ENDPOINT:
        options["AWS_S3_ENDPOINT"] = settings.LAKE_S3_ENDPOINT
        options["AWS_VIRTUAL_HOSTING"] = "FALSE" if settings.LAKE_S3_URL_STYLE == "path" else "TRUE"
        options["AWS_HTTPS"] = "YES" if settings.LAKE_S3_USE_SSL else "NO"
    return options


def _env():
    """A `rasterio.Env` pointed at the lake, for one read.

    Scoped to the `with` block and to this thread: nothing is written into the
    process's environment, so the keys cannot leak into another library.
    rasterio takes credentials only through a session (it refuses them as
    plain options). With no keys set the session falls back to the ambient
    AWS credentials, as DuckDB's credential chain does. With nothing set at
    all there is no session: a local path, which is what the tests read.
    """
    rasterio = _rasterio()
    from rasterio.session import AWSSession

    session = None
    has_keys = bool(settings.LAKE_S3_ACCESS_KEY and settings.LAKE_S3_SECRET_KEY)
    if has_keys:
        session = AWSSession(
            aws_access_key_id=settings.LAKE_S3_ACCESS_KEY,
            aws_secret_access_key=settings.LAKE_S3_SECRET_KEY,
            region_name=settings.LAKE_S3_REGION or None,
        )
    elif settings.LAKE_S3_ENDPOINT or settings.LAKE_S3_REGION:
        session = AWSSession(region_name=settings.LAKE_S3_REGION or None)
    return rasterio.Env(session=session, **_options())


class _Clock:
    """How long a read has run, and how long its current step has.

    A step is one stretch of work that goes to the lake: the open, one chunk
    of rows of a statistics read, one strip of a clip. GDAL bounds each
    request it makes; this bounds the read as a whole, between steps, since
    nothing can stop GDAL inside one. A limit of zero or less is no limit.
    """

    def __init__(self, max_seconds: float) -> None:
        self.max_seconds = max_seconds
        self.started = self.step_started = time.monotonic()

    def step(self) -> None:
        """Begin the next step, or give the read up if it has run too long."""
        now = time.monotonic()
        if self.max_seconds > 0 and now - self.started > self.max_seconds:
            logger.warning("A raster read was given up on after %.0f seconds", now - self.started)
            raise RasterUnavailable("the read ran past its time limit")
        self.step_started = now

    def stalled(self) -> bool:
        """Whether the step now running has waited as long as a stalled request does."""
        return time.monotonic() - self.step_started >= _STALL_SECONDS - 0.5


def read_stats(
    uri: str,
    *,
    max_pixels: int,
    bbox: tuple[float, float, float, float] | None = None,
    area: str | None = None,
    max_seconds: float = READ_SECONDS,
) -> dict:
    """What a raster's pixels say inside a place: per-band figures and class shares.

    `bbox` is `(min_lon, min_lat, max_lon, max_lat)` and `area` a drawn polygon
    as WKT, both SRID 4326; with an area, `bbox` is its envelope, as the lake's
    readers take it. With neither, the whole raster is in scope. The place is
    cut to the raster's footprint, moved into the raster's CRS, and only the
    window over it is read. A pixel counts when its centre is inside the place
    and it holds data (not nodata). A place smaller than a pixel counts the
    pixels it touches.

    A window above `max_pixels` is read at reduced size, with nearest-neighbour
    resampling so a class stays a class, and the answer says `approximate`.
    On a COG that read comes from an overview, so it stays cheap. A raster
    with no overview is read at full size, a slice at a time, and thinned
    here (`_thinned`). Never more than `max_pixels` are counted.

    The window is read a chunk of rows at a time, every band of a chunk in
    one request to GDAL, and the figures are added up as it goes: the pixels
    are never held whole. A read still going after `max_seconds` stops before
    its next chunk and raises `RasterUnavailable` (zero or less: no limit).
    `RasterNotPlaceable` means the raster's extent has no lon/lat box, so no
    place can be put on it; with no place it still reads.

    Returns `pixels` (inside the place, on the grid that was read),
    `approximate`, `bands` (`index`, `min`, `max`, `mean`, `valid_percent`; an
    alpha band is not one) and, for a classified raster — one whole-number
    band with a legend in its tags — `classes` (`value`, `name`, `pixels`,
    `share` of the valid pixels, largest first, at most `MAX_CLASSES`) and
    `other_classes` (`values`, `pixels`, `share`: every value beyond those,
    summed; None when there is none). Both are None for any other raster. A
    place that misses the raster is `pixels: 0` with no figures, not an error.
    """
    ring = _ring(bbox, area)
    rasterio = _rasterio()
    clock = _Clock(max_seconds)
    try:
        with _env(), rasterio.open(uri) as source:
            return _stats(source, ring, int(max_pixels), clock)
    except _read_failures() as exc:
        raise _classify(exc, clock) from exc


def clip(
    uri: str,
    *,
    bbox: tuple[float, float, float, float],
    max_bytes: int,
    max_seconds: float = READ_SECONDS,
) -> bytes:
    """The raster's pixels over a rectangle, as the bytes of a GeoTIFF.

    The window over `bbox` (SRID 4326), in the raster's own CRS and on its own
    grid: nothing is resampled, as in the data platform's export
    (`gobase/cli/export_raster.py`). The clip is the box, never a polygon
    mask: a drawn area is clipped to its envelope. Tiled and compressed, with
    the source's nodata or mask, colour table, band descriptions and the tags
    on `_DATASET_TAGS`.

    Raises `NoOverlap` when the box misses the raster, and `ClipTooLarge` when
    the window's pixels come to more than `max_bytes` before compression
    (width x height x bands x bytes per value). The check is made before any
    pixel is read. A read still going after `max_seconds` stops before its
    next strip and raises `RasterUnavailable`. `ClipNotWritten` means this
    server's own disk failed, not the lake. `RasterNotPlaceable` means the
    raster's extent has no lon/lat box.
    """
    ring = _ring(bbox, None)
    rasterio = _rasterio()
    clock = _Clock(max_seconds)
    try:
        with _env(), rasterio.open(uri) as source:
            return _clip(source, ring, int(max_bytes), clock)
    except _read_failures() as exc:
        raise _classify(exc, clock) from exc


def clip_size(uri: str, *, bbox: tuple[float, float, float, float], max_bytes: int) -> int:
    """How many bytes of pixels a clip of `bbox` would hold, without reading one.

    What a HEAD request asks: the raster's header is read, the window is
    worked out, and `NoOverlap` or `ClipTooLarge` is raised exactly as `clip`
    would raise it. No pixel is read and nothing is written.
    """
    ring = _ring(bbox, None)
    rasterio = _rasterio()
    clock = _Clock(READ_SECONDS)
    try:
        with _env(), rasterio.open(uri) as source:
            _, _, size = _clip_window(source, ring, int(max_bytes))
            return size
    except _read_failures() as exc:
        raise _classify(exc, clock) from exc


def _read_failures() -> tuple[type[BaseException], ...]:
    """The exceptions that mean "the read failed", as opposed to a bug here.

    rasterio's own, GDAL's raw ones, and the session's (a missing or refused
    credential). Anything else is this module's fault and must surface as
    one, not hide as "the raster could not be read".
    """
    from rasterio._err import CPLE_BaseError
    from rasterio.errors import CRSError, RasterioError

    failures: list[type[BaseException]] = [RasterioError, CPLE_BaseError, CRSError]
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:  # pragma: no cover - boto3 is a requirement
        pass
    else:
        failures += [BotoCoreError, ClientError]
    return tuple(failures)


def _ring(
    bbox: tuple[float, float, float, float] | None, area: str | None
) -> list[tuple[float, float]] | None:
    """The place as a closed ring of (lon, lat), or None for the whole raster."""
    if area is not None:
        match = _RING.match(area)
        if not match:
            # AreaField validated it; anything else is a caller's bug.
            raise ValueError("area must be the WKT AreaField wrote")
        ring = [tuple(float(n) for n in pair.split()) for pair in match.group(1).split(",")]
        return [(lon, lat) for lon, lat in ring]
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        return [
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ]
    return None


def _footprints(source) -> list[tuple[float, float, float, float]]:
    """The raster's extent as lon/lat boxes: one, or two when it crosses 180°.

    From the raster's four corners, so a rotated or south-up raster is covered
    too, with its edges cut into pieces before they are moved: the edge of a
    projected raster is a curve in lon/lat.

    A raster that crosses the antimeridian comes back with its west edge at a
    larger longitude than its east edge. Its extent is then two boxes, one on
    each side of the line, and a place is cut against both.

    A lon/lat grid may reach past 180° by less than a pixel: a whole-world
    grid whose pixels are centred on the round degrees (-180.5 to 180.5), or
    one a rounding error wider than the world. Its box is cut back to ±180;
    no place reaches past that line anyway.

    Raises `RasterNotPlaceable` when the extent has no lon/lat box at all: a
    whole-world raster in a projection that does not reach the corners of its
    own rectangle (Mollweide, Robinson). The same for a raster stored with
    longitudes that leave -180..180 by a pixel or more (0 to 360, as climate
    grids are): a place in the western half would miss it. A place cannot be
    put on such a raster reliably, and a wrong count is worse than none.
    """
    from rasterio.warp import transform_bounds

    corners = [
        source.transform @ point
        for point in ((0, 0), (source.width, 0), (source.width, source.height), (0, source.height))
    ]
    xs, ys = zip(*corners, strict=True)
    box = transform_bounds(
        source.crs, "EPSG:4326", min(xs), min(ys), max(xs), max(ys), densify_pts=_EDGE_POINTS
    )
    left, bottom, right, top = box
    if all(math.isfinite(n) for n in box) and left < right and source.crs.is_geographic:
        # Less than a pixel past the line is the grid's registration, not
        # another convention for longitude.
        pixel = (right - left) / source.width
        if left >= -180.0 - pixel and right <= 180.0 + pixel:
            left, right = max(left, -180.0), min(right, 180.0)
    if (
        not all(math.isfinite(n) for n in box)
        or left == right
        or bottom >= top
        or min(left, right) < -180.0 - 1e-9
        or max(left, right) > 180.0 + 1e-9
    ):
        logger.warning("A raster's extent has no lon/lat box, so no place can be put on it")
        raise RasterNotPlaceable("the raster's extent has no lon/lat box")
    # A hair wider, so a place that ends on the raster's edge is not cut short
    # by rounding.
    width = right - left if left < right else (180.0 - left) + (right + 180.0)
    pad_x, pad_y = width * 1e-6, (top - bottom) * 1e-6
    bottom, top = max(-90.0, bottom - pad_y), min(90.0, top + pad_y)
    if left < right:
        return [(max(-180.0, left - pad_x), bottom, min(180.0, right + pad_x), top)]
    return [(left - pad_x, bottom, 180.0, top), (-180.0, bottom, right + pad_x, top)]


def _cut(
    ring: list[tuple[float, float]], box: tuple[float, float, float, float]
) -> list[tuple[float, float]] | None:
    """A closed ring cut to a box, or None when nothing of it is inside.

    Sutherland-Hodgman, one side of the box at a time. A concave ring can
    come back with edges that run along the box's side; they enclose no
    area, so they count no pixel.
    """
    left, bottom, right, top = box
    points = ring[:-1]
    for axis, limit, keeps_above in (
        (0, left, True),
        (0, right, False),
        (1, bottom, True),
        (1, top, False),
    ):
        if not points:
            return None

        def inside(point, axis=axis, limit=limit, keeps_above=keeps_above):
            return point[axis] >= limit if keeps_above else point[axis] <= limit

        def crossing(start, end, axis=axis, limit=limit):
            share = (limit - start[axis]) / (end[axis] - start[axis])
            other = start[1 - axis] + share * (end[1 - axis] - start[1 - axis])
            return (limit, other) if axis == 0 else (other, limit)

        kept: list[tuple[float, float]] = []
        previous = points[-1]
        for current in points:
            if inside(current):
                if not inside(previous):
                    kept.append(crossing(previous, current))
                kept.append(current)
            elif inside(previous):
                kept.append(crossing(previous, current))
            previous = current
        points = kept
    if len(points) < 3:
        return None
    return [*points, points[0]]


def _shapes(source, ring: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """The place as rings in the raster's CRS: none when it misses the raster.

    The ring is cut to the raster's footprint in lon/lat first. A place far
    wider than the raster — a zoomed-out map, a whole country — has corners
    outside the area the raster's projection is defined for, and those cannot
    be moved at all: PROJ answers with an error or with infinity. What is
    left after the cut lies on the raster, where the projection works. Each
    edge is then cut into short pieces, because a straight edge in lon/lat is
    a curve in a projected CRS.

    One ring, or two for a raster that crosses the antimeridian and a place
    that reaches both sides of it.
    """
    from rasterio.warp import transform

    if source.crs is None:
        logger.warning("A raster has no CRS, so no place can be put on it")
        raise RasterNotPlaceable("the raster has no CRS")
    shapes = []
    for footprint in _footprints(source):
        piece = _cut(ring, footprint)
        if piece is None:
            continue
        dense: list[tuple[float, float]] = []
        for (x0, y0), (x1, y1) in zip(piece, piece[1:], strict=False):
            for step in range(_EDGE_POINTS):
                share = step / _EDGE_POINTS
                dense.append((x0 + (x1 - x0) * share, y0 + (y1 - y0) * share))
        dense.append(piece[-1])
        xs, ys = transform("EPSG:4326", source.crs, [x for x, _ in dense], [y for _, y in dense])
        if not all(math.isfinite(n) for n in (*xs, *ys)):
            # Not "misses": the place is on the raster and still could not be moved.
            raise RasterReadError("the place could not be put on the raster's CRS")
        shapes.append(list(zip(xs, ys, strict=True)))
    return shapes


def _span(low: float, high: float, size: int) -> tuple[int, int] | None:
    """The pixels `[start, stop)` a place covers along one axis, or None if none.

    Rounded outwards, so every pixel the place touches is inside. A place
    whose edge lies on a pixel edge lands a hair to one side of it in
    floating point; without the allowance it would take in a whole extra row
    or column of pixels it does not touch.

    A place with no width along the axis (a point, or a box whose two sides
    are the same) still covers a pixel: the one it is in, or the one that
    starts there when it sits exactly on a pixel edge.
    """
    if low > size + _PIXEL_EDGE or high < -_PIXEL_EDGE:
        return None
    start = math.floor(low + _PIXEL_EDGE)
    stop = math.ceil(high - _PIXEL_EDGE)
    no_width = high - low <= 2 * _PIXEL_EDGE
    if stop <= start:
        if not no_width:
            return None
        stop = start + 1
    start, stop = max(0, start), min(size, stop)
    if stop <= start:
        # Only a place with no width, sitting on the raster's far edge.
        return (size - 1, size) if no_width and start >= size else None
    return start, stop


def _window(source, shapes: list[list[tuple[float, float]]]):
    """The pixel window that covers shapes in the raster's CRS, or None if they miss it."""
    from rasterio.windows import Window

    if not shapes:
        return None
    inverse = ~source.transform
    cols, rows = zip(*(inverse @ point for shape in shapes for point in shape), strict=True)
    across = _span(min(cols), max(cols), source.width)
    down = _span(min(rows), max(rows), source.height)
    if across is None or down is None:
        return None
    return Window(across[0], down[0], across[1] - across[0], down[1] - down[0])


def _legend(source) -> dict[str, str] | None:
    """A classified raster's legend, `{"7": "built_area", ...}`, or None.

    The data platform writes it as JSON text in the file's `classes` tag
    (the catalog shows the same tag as `tags.default.classes`). A raster is
    classified when it has that legend and one whole-number band.
    """
    import numpy

    if source.count != 1 or numpy.dtype(source.dtypes[0]).kind not in "iu":
        return None
    return _parse_legend(source.tags().get("classes"))


def _parse_legend(raw) -> dict[str, str] | None:
    """The `classes` tag as a legend, or None when it is not one."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        legend = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(legend, dict) or not legend:
        return None
    return {str(code): str(name) for code, name in legend.items()}


def _reduced(width: int, height: int, max_pixels: int) -> tuple[int, int]:
    """The size a window is read at: itself, or smaller, never above the budget."""
    if width * height <= max_pixels:
        return width, height
    shrink = math.sqrt(width * height / max_pixels)
    out_width = max(1, math.floor(width / shrink))
    out_height = max(1, math.floor(height / shrink))
    # A very thin strip cannot shrink below one pixel across, so its long side
    # has to give the rest.
    if out_width * out_height > max_pixels:
        if out_width >= out_height:
            out_width = max(1, max_pixels // out_height)
        else:
            out_height = max(1, max_pixels // out_width)
    return out_width, out_height


def _chunk_rows(source, window, out_width: int, out_height: int, indexes: list[int]) -> int:
    """How many rows of the grid being read one chunk of a statistics read holds.

    Sized by what the chunk pulls from the lake, not by its own pixels. A COG
    is stored in blocks, and a block is fetched whole however little of it
    the window covers: a window 200 pixels wide over 512-pixel blocks pulls
    whole blocks all the way down. So a chunk is as many whole rows of blocks
    as come to about `_CHUNK_BLOCK_BYTES` before compression, and never more
    pixels than `_CHUNK_HELD_BYTES`.

    A reduced read is counted on what GDAL reads behind it. That is an
    overview when the raster has one coarse enough, whose blocks are the
    same size; then a row of the reduced grid is about a row of the
    overview. With no such overview GDAL reads the full-size blocks and
    keeps one pixel in so many, so one row of blocks is only a few rows of
    the reduced grid, and a chunk is that few.
    """
    import numpy

    block_height, block_width = source.block_shapes[0]
    block_height = max(1, min(int(block_height), source.height))
    block_width = max(1, min(int(block_width), source.width))
    # How many rows of the raster one row of the grid stands for, and how
    # many rows of the overview GDAL takes them from.
    shrink = max(1.0, window.height / out_height)
    factor = _overview_factor(source, indexes[0], shrink)
    rows_behind = max(1.0, shrink / factor)
    first = int(window.col_off / factor) // block_width
    last = int((window.col_off + window.width - 1) / factor) // block_width
    across = max(1, last - first + 1)
    # Every band of a block comes with it when the bands are stored together.
    block_bytes = (
        block_height * block_width * sum(numpy.dtype(dtype).itemsize for dtype in source.dtypes)
    )
    block_rows = max(1, _CHUNK_BLOCK_BYTES // max(1, block_bytes * across))
    rows = max(1, int(block_rows * block_height / rows_behind))
    # The pixels of the bands read, and a mask byte for each.
    row_bytes = out_width * sum(numpy.dtype(source.dtypes[i - 1]).itemsize + 1 for i in indexes)
    held = max(1, _CHUNK_HELD_BYTES // max(1, row_bytes))
    if held < rows:
        # Whole rows of blocks when even one fits; otherwise what fits.
        rows = held // block_height * block_height or held
    return max(1, min(rows, out_height))


def _overview_factor(source, index: int, shrink: float) -> int:
    """How much smaller the overview GDAL reads a reduced window from is: 1 for none.

    GDAL takes the coarsest overview that is still fine enough for the size
    asked for, and allows itself one a little coarser (a fifth).
    """
    if shrink <= 1:
        return 1
    return max((f for f in source.overviews(index) if f <= shrink * 1.2), default=1)


def _thinned(source, indexes: list[int], window, out_shape: tuple[int, int], rows, clock: _Clock):
    """Rows `rows = (first, stop)` of a window's reduced grid, from the full-size pixels.

    For a raster with no overview to read a reduced window from. GDAL would
    do the same thing itself, one row of the reduced grid at a time, and for
    each such row it needs every block the row crosses. When those do not fit
    its cache together it fetches and unpacks them again for every row: on a
    wide image that is thousands of times over. So the full-size rows are
    read here instead, a slice of them at a time, and the pixels GDAL would
    have kept are kept: the pixel under the centre of each cell of the
    reduced grid (nearest neighbour). A slice no kept row falls in is not
    read at all.

    Returns the pixels and their mask, `(bands, stop - first, out_width)`
    each. The clock is looked at before each slice.
    """
    import numpy
    from rasterio.windows import Window

    out_height, out_width = out_shape
    first, stop = rows
    col_off, row_off = int(window.col_off), int(window.row_off)
    width, height = int(window.width), int(window.height)
    # GDAL's own rule for the pixel a cell keeps, its small allowance included.
    kept_rows = numpy.minimum(
        ((numpy.arange(first, stop) + 0.5) * (height / out_height) + 1e-10).astype(numpy.int64),
        height - 1,
    )
    kept_cols = numpy.minimum(
        ((numpy.arange(out_width) + 0.5) * (width / out_width) + 1e-10).astype(numpy.int64),
        width - 1,
    )
    dtypes = [numpy.dtype(source.dtypes[index - 1]) for index in indexes]
    data = numpy.empty((len(indexes), stop - first, out_width), dtype=numpy.result_type(*dtypes))
    hidden = numpy.empty(data.shape, dtype=bool)
    row_bytes = width * sum(dtype.itemsize + 1 for dtype in dtypes)
    slice_rows = max(1, _CHUNK_HELD_BYTES // max(1, row_bytes))
    top, bottom = int(kept_rows[0]), int(kept_rows[-1]) + 1
    for start in range(top, bottom, slice_rows):
        end = min(bottom, start + slice_rows)
        wanted = (kept_rows >= start) & (kept_rows < end)
        if not wanted.any():
            continue
        clock.step()
        full = source.read(
            indexes, window=Window(col_off, row_off + start, width, end - start), masked=True
        )
        picked = numpy.ix_(range(len(indexes)), kept_rows[wanted] - start, kept_cols)
        data[:, wanted, :] = full.data[picked]
        hidden[:, wanted, :] = numpy.ma.getmaskarray(full)[picked]
        del full
    return data, hidden


def _row_chunks(start: int, height: int, rows: int) -> list[tuple[int, int]]:
    """`[first, stop)` rows of a window `height` tall, `rows` at a time.

    `start` is the window's first row in the raster. Chunks end on a multiple
    of `rows` counted from the raster's top, so a chunk of whole block rows
    covers whole blocks and no block is fetched for two chunks.
    """
    chunks = []
    first = 0
    while first < height:
        stop = min(height, ((start + first) // rows + 1) * rows - start)
        chunks.append((first, stop))
        first = stop
    return chunks


def _stats(source, ring: list[tuple[float, float]] | None, max_pixels: int, clock: _Clock) -> dict:
    import numpy
    from affine import Affine
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.features import geometry_mask
    from rasterio.windows import Window

    legend = _legend(source)
    empty = {
        "pixels": 0,
        "approximate": False,
        "bands": [],
        "classes": [] if legend is not None else None,
        "other_classes": None,
    }
    if ring is None:
        shapes = None
        window = Window(0, 0, source.width, source.height)
    else:
        shapes = _shapes(source, ring)
        window = _window(source, shapes)
    if window is None:
        return empty

    width, height = int(window.width), int(window.height)
    out_width, out_height = _reduced(width, height, max(1, max_pixels))
    approximate = (out_width, out_height) != (width, height)
    out_shape = (out_height, out_width)

    if shapes is None:
        inside = numpy.ones(out_shape, dtype=bool)
    else:
        grid = source.window_transform(window) @ Affine.scale(
            width / out_width, height / out_height
        )
        geometries = [{"type": "Polygon", "coordinates": [shape]} for shape in shapes]
        inside = geometry_mask(geometries, out_shape=out_shape, transform=grid, invert=True)
        if not inside.any():
            # Smaller than a pixel: no centre is inside. Count what it touches.
            inside = geometry_mask(
                geometries, out_shape=out_shape, transform=grid, invert=True, all_touched=True
            )
        if not inside.any() and min(out_shape) == 1:
            # A place with no width, lying exactly on a pixel edge: it touches
            # nothing by the rule above. The window is the pixels that start
            # at that edge, so those are the ones it counts.
            inside[:] = True
    pixels = int(inside.sum())
    if pixels == 0:
        return empty

    # An alpha band is transparency, not data. It still decides which pixels
    # of the other bands hold data: `masked=True` reads it as their mask.
    indexes = [
        index for index in source.indexes if source.colorinterp[index - 1] != ColorInterp.alpha
    ]
    tallies = [_Tally(numpy.dtype(source.dtypes[index - 1])) for index in indexes]
    counts: dict[int, int] = {}

    # A chunk of rows at a time, every band of it in one read. Read band by
    # band, a raster that stores its bands together was fetched once for each
    # band; read whole, nothing could look at the clock until a band was in.
    col_off, row_off = int(window.col_off), int(window.row_off)
    rows = _chunk_rows(source, window, out_width, out_height, indexes) if indexes else out_height
    scale = height / out_height
    from_overview = (
        approximate and bool(indexes) and _overview_factor(source, indexes[0], scale) > 1
    )
    # On a reduced grid a chunk's rows are not the raster's own, so they
    # cannot follow its blocks: counted from the window's top.
    for first, stop in _row_chunks(0 if approximate else row_off, out_height, rows):
        if not indexes:
            break
        if not approximate:
            clock.step()
            read = source.read(
                indexes, window=Window(col_off, row_off + first, width, stop - first), masked=True
            )
            data, hidden = read.data, numpy.ma.getmaskarray(read)
        elif from_overview:
            # The same rows of the reduced grid the whole window would give:
            # the chunk's share of the window, at the chunk's share of the size.
            clock.step()
            read = source.read(
                indexes,
                window=Window(col_off, row_off + first * scale, width, (stop - first) * scale),
                out_shape=(len(indexes), stop - first, out_width),
                resampling=Resampling.nearest,
                masked=True,
            )
            data, hidden = read.data, numpy.ma.getmaskarray(read)
        else:
            # No overview to read from: the same pixels, picked here.
            data, hidden = _thinned(source, indexes, window, out_shape, (first, stop), clock)
        for position, tally in enumerate(tallies):
            values = data[position][inside[first:stop] & ~hidden[position]]
            if values.dtype.kind == "f":
                # NaN and infinity are not data, whatever the file's nodata says.
                values = values[numpy.isfinite(values)]
            tally.add(values)
            if legend is not None:
                found, found_counts = numpy.unique(values, return_counts=True)
                for value, count in zip(found.tolist(), found_counts.tolist(), strict=True):
                    counts[value] = counts.get(value, 0) + count
        del data, hidden

    bands = [
        {
            "index": index,
            "min": tally.low,
            "max": tally.high,
            "mean": tally.mean(),
            "valid_percent": _figure(100.0 * tally.count / pixels),
        }
        for index, tally in zip(indexes, tallies, strict=True)
    ]
    classes, other_classes = _classes(counts, legend) if legend is not None else (None, None)
    return {
        "pixels": pixels,
        "approximate": approximate,
        "bands": bands,
        "classes": classes,
        "other_classes": other_classes,
    }


class _Tally:
    """One band's figures, added up a chunk at a time.

    The sum of a band of whole numbers of up to 32 bits is kept as a whole
    number, so its mean is exact however the rows were chunked. Wider whole
    numbers and floats are summed as 64-bit floats, chunk by chunk.
    """

    def __init__(self, dtype) -> None:
        self.exact = dtype.kind in "iu" and dtype.itemsize <= 4
        self.count = 0
        self.total = 0 if self.exact else 0.0
        self.low = None
        self.high = None

    def add(self, values) -> None:
        import numpy

        if not values.size:
            return
        self.count += int(values.size)
        if self.exact:
            self.total += int(values.sum(dtype=numpy.int64))
        else:
            self.total += float(values.sum(dtype=numpy.float64))
        low, high = _number(values.min()), _number(values.max())
        self.low = low if self.low is None else min(self.low, low)
        self.high = high if self.high is None else max(self.high, high)

    def mean(self) -> float | None:
        return _figure(self.total / self.count) if self.count else None


def _classes(counts: dict[int, int], legend: dict[str, str]) -> tuple[list[dict], dict | None]:
    """Each value's pixel count and share of the valid pixels, largest first.

    At most `MAX_CLASSES` rows. Every value beyond them is summed into the
    second answer, so nothing is dropped without a word and the shares still
    add up to 1.
    """
    total = sum(counts.values())
    rows = [
        {
            "value": int(value),
            "name": legend.get(str(int(value))),
            "pixels": int(count),
            "share": _figure(int(count) / total),
        }
        for value, count in counts.items()
    ]
    rows.sort(key=lambda row: (-row["pixels"], row["value"]))
    rest = rows[MAX_CLASSES:]
    other = None
    if rest:
        rest_pixels = sum(row["pixels"] for row in rest)
        other = {"values": len(rest), "pixels": rest_pixels, "share": _figure(rest_pixels / total)}
    return rows[:MAX_CLASSES], other


def _figure(value: float) -> float:
    """A figure to nine significant digits.

    Significant digits, not decimal places: a mean of 3e-9 or a share of one
    pixel in ten million is small, not zero, and rounding to a fixed place
    would report it as nothing.
    """
    return float(f"{value:.9g}")


def _number(value):
    """A numpy scalar as a plain number: whole numbers stay whole."""
    number = value.item()
    return number if isinstance(number, int) else _figure(float(number))


def _carries_mask(source) -> bool:
    """Whether the raster marks its empty pixels with a mask of its own.

    A mask stored with the dataset, as opposed to a nodata value or an alpha
    band, which a clip carries anyway (the profile and the band).
    """
    from rasterio.enums import MaskFlags

    return any(
        MaskFlags.per_dataset in flags
        and MaskFlags.alpha not in flags
        and MaskFlags.nodata not in flags
        for flags in source.mask_flag_enums
    )


def _clip_window(source, ring: list[tuple[float, float]], max_bytes: int):
    """The window a clip of the ring covers, the bytes in one of its rows, and in all.

    Raises `NoOverlap` or `ClipTooLarge`. Reads the raster's header only.
    """
    import numpy

    window = _window(source, _shapes(source, ring))
    if window is None:
        raise NoOverlap()
    width, height = int(window.width), int(window.height)
    row_bytes = width * sum(numpy.dtype(dtype).itemsize for dtype in source.dtypes)
    size = row_bytes * height
    if size > max_bytes:
        raise ClipTooLarge(size, max_bytes, width * height)
    return window, row_bytes, size


def _not_written(exc: BaseException) -> ClipNotWritten:
    """A failure to write the clip on this server, logged by type: no path."""
    kind = type(exc).__name__
    logger.error("A clip could not be written to local disk: %s", kind)
    return ClipNotWritten(kind)


def _clip(source, ring: list[tuple[float, float]], max_bytes: int, clock: _Clock) -> bytes:
    from rasterio.windows import Window

    rasterio = _rasterio()

    window, row_bytes, _ = _clip_window(source, ring, max_bytes)
    width, height = int(window.width), int(window.height)

    profile = {
        "driver": "GTiff",
        "dtype": source.dtypes[0],
        "count": source.count,
        "crs": source.crs,
        "nodata": source.nodata,
        "width": width,
        "height": height,
        "transform": source.window_transform(window),
        "tiled": True,
        "blockxsize": _BLOCK,
        "blockysize": _BLOCK,
        "compress": "deflate",
    }
    # Moved a strip of whole blocks at a time, into a temporary file on local
    # disk: the clip is never held as one array, and never twice. Built in
    # GDAL's memory instead, the same clip held three copies of itself at its
    # peak (context/integrations/raster.md). The bytes handed back are the
    # one copy.
    #
    # Reading and writing fail apart. A failed read is the lake's or the
    # raster's; a failed write is this server's disk, and says so
    # (`ClipNotWritten`), never "the raster could not be read".
    strip = max(_BLOCK, (_STRIP_BYTES // max(1, row_bytes)) // _BLOCK * _BLOCK)
    masked = _carries_mask(source)
    failures = (*_read_failures(), OSError)
    try:
        folder = tempfile.TemporaryDirectory(prefix="clip-")
    except OSError as exc:
        raise _not_written(exc) from exc
    with folder:
        path = os.path.join(folder.name, "clip.tif")
        try:
            clipped = rasterio.open(path, "w", **profile)
        except failures as exc:
            raise _not_written(exc) from exc
        try:
            for row in range(0, height, strip):
                rows = min(strip, height - row)
                read = Window(window.col_off, window.row_off + row, width, rows)
                written = Window(0, row, width, rows)
                clock.step()
                pixels = source.read(window=read)
                mask = source.dataset_mask(window=read) if masked else None
                try:
                    clipped.write(pixels, window=written)
                    if mask is not None:
                        clipped.write_mask(mask, window=written)
                except failures as exc:
                    raise _not_written(exc) from exc
            try:
                _carry_metadata(source, clipped)
            except failures as exc:
                raise _not_written(exc) from exc
        except BaseException:
            # Whatever went wrong, the half-written file is closed quietly:
            # the first failure is the one to report.
            with contextlib.suppress(Exception):
                clipped.close()
            raise
        try:
            # Closing writes what is still held, so it can fail like a write.
            clipped.close()
            with open(path, "rb") as written_clip:
                return written_clip.read()
        except failures as exc:
            raise _not_written(exc) from exc


def _carry_metadata(source, clipped) -> None:
    """Copy what a raster profile does not carry: palette, tags, band descriptions.

    Without these a land-cover clip is anonymous integers: no legend, no
    colours. As the data platform's `_carry_metadata` does, except that only
    the tags on the list are carried.
    """
    try:
        clipped.colorinterp = source.colorinterp
    except Exception:  # noqa: BLE001 - some interpretations cannot be set on GTiff
        pass
    clipped.update_tags(**_dataset_tags(source.tags()))
    for index in source.indexes:
        band_tags = {
            key: value
            for key, value in source.tags(index).items()
            if key.startswith(_BAND_TAG_PREFIX) and not _holds_a_slash(value)
        }
        if band_tags:
            clipped.update_tags(index, **band_tags)
        try:
            colormap = source.colormap(index)
        except ValueError:
            colormap = None
        if colormap:
            clipped.write_colormap(index, colormap)
        description = source.descriptions[index - 1]
        if description and not _names_a_path(description):
            clipped.set_band_description(index, description)
    if any(scale != 1.0 for scale in source.scales):
        clipped.scales = source.scales
    if any(offset != 0.0 for offset in source.offsets):
        clipped.offsets = source.offsets
    if any(source.units):
        clipped.units = source.units


def _dataset_tags(tags: dict) -> dict[str, str]:
    """The tags a clip carries: on the list, and not naming a place in a store.

    Three rules, by what the tag is. The legend is written again from what
    was read of it (`_carried_legend`), never passed on as the text it came
    in. A tag that holds a sentence is carried unless it has the shape of a
    path. Any other tag is a short value and is dropped if it holds a slash
    at all.
    """
    carried = {}
    for key, value in tags.items():
        if key not in _DATASET_TAGS or not isinstance(value, str):
            continue
        if key == "classes":
            legend = _carried_legend(value)
            if legend is not None:
                carried[key] = legend
            continue
        if key in _PROSE_TAGS:
            keep = not _names_a_path(value)
        else:
            keep = not _holds_a_slash(value)
        if keep:
            carried[key] = value
    return carried


def _carried_legend(raw) -> str | None:
    """The legend a clip carries, as JSON text, or None when nothing of it may go.

    Only what a legend is: a whole-number value and the name of its class. An
    entry whose key is not a whole number, whose name is not text, or whose
    name has the shape of a path is left out, so the tag cannot carry
    anything else in a legend's clothes. Written again from the entries kept,
    in their order.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        legend = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(legend, dict):
        return None
    kept = {
        code: name
        for code, name in legend.items()
        if _WHOLE_NUMBER.match(code) and isinstance(name, str) and not _names_a_path(name)
    }
    return json.dumps(kept, ensure_ascii=False) if kept else None


def _holds_a_slash(value) -> bool:
    return isinstance(value, str) and ("/" in value or "\\" in value)


def _names_a_path(value) -> bool:
    """Whether a sentence names a place in a file system or in the lake.

    The second check, never the only one: the list of tags is the first. Any
    backslash or `://` counts. Otherwise a word with a slash in it counts
    when it also looks like a path: two slashes or more, a leading `/`, `.`
    or `~`, a `:` or `=` (a host and port, a `key=value`), or a file
    extension at its end. "Land Use/Land Cover" and "ratio 1/2" are not
    paths; a single `folder/name` with no extension is not told from them.
    """
    if not isinstance(value, str):
        return False
    if "\\" in value or "://" in value:
        return True
    for word in value.split():
        # A slash standing alone between two words joins them; it names nothing.
        if "/" not in word or not word.strip("/"):
            continue
        if (
            word.count("/") >= 2
            or word[0] in "/.~"
            or ":" in word
            or "=" in word
            or _FILE_END.search(word)
        ):
            return True
    return False


def _classify(exc: BaseException, clock: _Clock | None = None) -> Exception:
    """Decide whether a failed read means the lake is down or the object is bad.

    Reported by exception type only: a GDAL message quotes the object's path,
    and a session failure can quote the endpoint and the key id.

    A lake that sends a response's headers and then stalls is the one case
    the message cannot tell: GDAL gives the request up, keeps the few bytes
    it got, and reports a file it cannot read ("Cannot read TIFF header").
    The clock tells it instead. A step that failed after waiting as long as a
    stalled request does was stalled, so the lake is unavailable. A bad file
    fails at once.
    """
    if isinstance(
        exc, (RasterUnavailable, RasterReadError, RasterNotPlaceable, NoOverlap, ClipTooLarge)
    ):
        return exc
    kind = type(exc).__name__
    message = str(exc).lower()
    if kind in _UNAVAILABLE_TYPES or any(marker in message for marker in _UNAVAILABLE_MARKERS):
        logger.warning("Lake unreachable while reading a raster: %s", kind)
        return RasterUnavailable(kind)
    if clock is not None and clock.stalled():
        logger.warning("Lake stalled while reading a raster: %s", kind)
        return RasterUnavailable(kind)
    logger.warning("Unreadable raster: %s", kind)
    return RasterReadError(kind)
