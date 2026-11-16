"""The Map API for rasters.

Two ways to a raster's pixels. A desktop client reads the whole COG itself,
with short-lived credentials from `raster-access` (docs/adr/022). The portal
reads a window of it for `raster-stats` and `clip.tif`, which the Ask agent's
`raster_clip` tool uses (docs/adr/024, docs/adr/029).

Its own module so it stays apart from views.py, which the features endpoint
keeps busy (docs/adr/015).
"""

import hashlib
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.http import content_disposition_header, parse_etags
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import kb

from . import raster, sts
from .http import LakeFailed, LakeUnreachable, cacheable
from .serializers import (
    RasterAccessSerializer,
    RasterClipQuerySerializer,
    RasterPlaceQuerySerializer,
    RasterStatsSerializer,
)

logger = logging.getLogger(__name__)


class RasterAccessNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "This portal does not serve rasters to desktop clients"


class ClipNotWritten(APIException):
    """This server could not write the clip to its own disk.

    A 503, not a 500 and not the lake's 502: the request is good and the
    raster is good; the temporary folder was full or could not be written,
    which other clips finishing can clear. The lake is not blamed for it.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The portal could not write the clip. Try again later."


class RasterNotPlaceable(APIException):
    """No place can be put on this raster: its extent has no lon/lat box.

    A 422: the request is well formed and the lake and the file are fine, but
    this raster's layout is one the reader does not support (a whole-world
    grid in Mollweide, longitudes from 0 to 360). Not the lake's 502, which
    would say a good file could not be read. Without a place the raster is
    still measured whole (docs/adr/029).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = (
        "This raster cannot be measured or clipped over a place: its extent has "
        "no longitude and latitude box. Without a place, the whole raster is measured."
    )


_NOT_PLACEABLE = OpenApiResponse(
    description=(
        "No place can be put on this raster: its extent has no longitude and "
        "latitude box. The message says so."
    )
)


def _held_copy_matches(request, etag: str) -> bool:
    """Whether `If-None-Match` names this ETag: the weak comparison RFC 9110 asks for.

    `W/"x"` and `"x"` are the same copy for this purpose, whichever of the two
    the client sent back.
    """
    held = parse_etags(request.headers.get("If-None-Match", ""))
    if "*" in held:
        return True
    return etag.removeprefix("W/") in {tag.removeprefix("W/") for tag in held}


class RasterAccessView(APIView):
    """Short-lived, read-only lake credentials for one raster, and its address.

    ArcGIS Pro cannot open a COG from a URL. It reads one through a cloud
    storage connection, which signs its own range requests to the bucket, so
    the portal hands out what that connection needs and never the pixels
    (docs/adr/022). Raster only: any other asset is a 404, as `/data` is for
    anything but a vector.

    A GET although each call issues new credentials: an API key may only
    read (docs/adr/021), and nothing in the portal or the lake changes.
    """

    @extend_schema(
        responses={
            200: RasterAccessSerializer,
            404: OpenApiResponse(description="No active raster asset with that id."),
            502: OpenApiResponse(
                description="The lake answered with an error, or the raster is not in the lake."
            ),
            503: OpenApiResponse(
                description=(
                    "Raster access is not set up on this portal, or the lake could not be reached."
                )
            ),
        },
        operation_id="map_asset_raster_access",
        summary="Credentials to read a raster from the lake",
        tags=["map"],
    )
    def get(self, request, asset_id):
        if not sts.configured():
            raise RasterAccessNotConfigured()

        uri = kb.raster_source_uri(asset_id)
        if uri is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            bucket, key = sts.split_s3_uri(uri)
        except ValueError as exc:
            # The catalog's fault, not the caller's: every raster should be in the lake.
            logger.error("Raster %s is not an s3:// object, so it cannot be shared", asset_id)
            raise LakeFailed() from exc

        try:
            credentials = sts.issue(bucket, key, session_name=f"portal-user-{request.user.pk}")
        except sts.IssuerUnavailable as exc:
            raise LakeUnreachable() from exc
        except sts.IssueFailed as exc:
            raise LakeFailed() from exc

        logger.info("Raster credentials for %s issued to user %s", asset_id, request.user.pk)
        body = RasterAccessSerializer(
            {
                "asset_id": asset_id,
                "url": sts.object_url(bucket, key),
                "endpoint": sts.public_endpoint(),
                "region": sts.region(),
                "bucket": bucket,
                "key": key,
                "credentials": credentials,
            }
        ).data
        response = Response(body)
        # The body is a secret. No cache, private or shared, may keep it.
        response["Cache-Control"] = "no-store"
        return response


class RasterStatsView(APIView):
    """What one raster's pixels say inside a place: band figures and class shares.

    For answers (docs/adr/029). The portal reads only the window over the
    place, a chunk of rows at a time, and counts at most
    `RASTER_STATS_MAX_PIXELS`: a larger place is read at reduced size and
    the answer says `approximate`. The body is figures, never pixels. Raster
    only: any other asset is a 404. A raster no place can be put on is a 422
    that says so; with no place it is still measured whole.

    A place that misses the raster is a 200 with `pixels: 0`: the honest
    answer to "what is here" is "nothing", not an error.
    """

    @extend_schema(
        parameters=[RasterPlaceQuerySerializer],
        responses={
            200: RasterStatsSerializer,
            400: OpenApiResponse(description="An unreadable bbox or area, or both."),
            404: OpenApiResponse(description="No active raster asset with that id."),
            422: _NOT_PLACEABLE,
            502: OpenApiResponse(description="The raster could not be read."),
            503: OpenApiResponse(
                description="The lake could not be reached, or the read ran past its time limit."
            ),
        },
        operation_id="map_asset_raster_stats",
        summary="Raster statistics over a place",
        tags=["map"],
    )
    def get(self, request, asset_id):
        query = RasterPlaceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        asked = query.validated_data

        source = kb.raster_source(asset_id)
        if source is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        area = asked.get("area")
        try:
            figures = raster.read_stats(
                source["source_uri"],
                max_pixels=settings.RASTER_STATS_MAX_PIXELS,
                bbox=area.envelope if area else asked.get("bbox"),
                area=area.wkt if area else None,
                max_seconds=settings.RASTER_READ_TIMEOUT_SECONDS,
            )
        except raster.RasterNotPlaceable as exc:
            raise RasterNotPlaceable() from exc
        except raster.RasterUnavailable as exc:
            raise LakeUnreachable() from exc
        except raster.RasterReadError as exc:
            raise LakeFailed() from exc

        return Response(RasterStatsSerializer({"asset_id": asset_id, **figures}).data)


# Bump whenever the same request could now get a different file: a change to
# how the window is worked out, to what the clip carries, or to how it is
# written. Every clip's ETag carries it, as the features page's does
# (docs/adr/015).
CLIP_FORMAT = 1


def _clip_etag(asset_id, bbox) -> str:
    """The ETag for one clip, worked out without reading the raster.

    Assets are content-addressed: changed pixels get a new asset id. So the
    id, the box and the format version decide the file.
    """
    key = f"clip|{CLIP_FORMAT}|{asset_id}|{bbox}"
    return f'W/"{hashlib.sha256(key.encode()).hexdigest()[:32]}"'


class RasterClipView(APIView):
    """One raster's pixels over a place, as a GeoTIFF to download.

    The window over the place's envelope, in the raster's own CRS and on its
    own grid, with its nodata, colours and legend (docs/adr/029). A rectangle,
    never a polygon mask: a drawn area is clipped to its envelope. The
    response is held whole, so it is capped by size, not by pixel count: a window whose
    pixels come to more than `RASTER_CLIP_MAX_BYTES` before compression
    (width x height x bands x bytes per value) is a 400 that says how large
    it was. The whole raster is not a clip; a desktop client reads it
    through `raster-access`.

    Cached as the document PDF is: an ETag and `private, no-cache`, so a
    browser keeps the file and asks before reusing it, and a match is a 304
    with no lake read. A HEAD request answers with the same status and
    headers a GET would, from the raster's header alone: it builds no clip,
    so its `Content-Length` is 0 and not the file's.

    Raster only: any other asset is a 404.
    """

    @extend_schema(
        parameters=[RasterClipQuerySerializer],
        responses={
            (200, "image/tiff"): OpenApiTypes.BINARY,
            304: OpenApiResponse(
                description=(
                    "The ETag sent in If-None-Match still matches; use the copy already held."
                )
            ),
            400: OpenApiResponse(
                description=(
                    "An unreadable bbox or area, both, or neither; a place that "
                    "does not overlap the raster; or a place too large to clip "
                    "(the message says how large its pixels are, uncompressed, "
                    "and how large a clip may be)."
                )
            ),
            404: OpenApiResponse(description="No active raster asset with that id."),
            422: _NOT_PLACEABLE,
            502: OpenApiResponse(description="The raster could not be read."),
            503: OpenApiResponse(
                description=(
                    "The lake could not be reached, the read ran past its time "
                    "limit, or the portal could not write the clip to its own disk."
                )
            ),
        },
        operation_id="map_asset_raster_clip",
        summary="A raster clipped to a place, as a GeoTIFF",
        tags=["map"],
    )
    def get(self, request, asset_id):
        return self._answer(request, asset_id, build=True)

    def head(self, request, asset_id):
        # Django would answer HEAD by running `get` and dropping the body:
        # a whole clip read and written to be thrown away.
        return self._answer(request, asset_id, build=False)

    def _answer(self, request, asset_id, *, build: bool):
        query = RasterClipQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        asked = query.validated_data

        # The lake URI is resolved here and never leaves the server.
        source = kb.raster_source(asset_id)
        if source is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        area = asked.get("area")
        sent = "area" if area else "bbox"
        bbox = area.envelope if area else asked["bbox"]

        # Checked after the catalog, not before: a superseded raster must
        # answer 404, not tell the browser its old copy is still good.
        etag = _clip_etag(asset_id, tuple(bbox))
        if _held_copy_matches(request, etag):
            return cacheable(HttpResponseNotModified(), etag)

        data = b""
        try:
            if build:
                data = raster.clip(
                    source["source_uri"],
                    bbox=bbox,
                    max_bytes=settings.RASTER_CLIP_MAX_BYTES,
                    max_seconds=settings.RASTER_READ_TIMEOUT_SECONDS,
                )
            else:
                raster.clip_size(
                    source["source_uri"], bbox=bbox, max_bytes=settings.RASTER_CLIP_MAX_BYTES
                )
        except raster.NoOverlap as exc:
            raise ValidationError({sent: ["This place does not overlap the raster."]}) from exc
        except raster.ClipTooLarge as exc:
            raise ValidationError(
                {
                    sent: [
                        f"This place is too large to clip: it covers {exc.pixels:,} "
                        f"pixels, {_size(exc.size)} uncompressed, and a clip "
                        f"may hold at most {_size(exc.allowed)}. "
                        "Ask for a smaller place."
                    ]
                }
            ) from exc
        except raster.ClipNotWritten as exc:
            raise ClipNotWritten() from exc
        except raster.RasterNotPlaceable as exc:
            raise RasterNotPlaceable() from exc
        except raster.RasterUnavailable as exc:
            raise LakeUnreachable() from exc
        except raster.RasterReadError as exc:
            raise LakeFailed() from exc

        response = HttpResponse(data, content_type="image/tiff")
        response["Content-Disposition"] = content_disposition_header(
            True, f"{source['name']}_clip.tif"
        )
        if build:
            # Only a GET knows the file's length. A HEAD knows the pixels'
            # size, not the compressed file's, so it sets none; Django then
            # writes the length of its empty body, 0, which says nothing
            # about the file.
            response["Content-Length"] = str(len(data))
        return cacheable(response, etag)


def _size(size: int) -> str:
    """A byte count for a message: megabytes, or kilobytes below one."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):,.1f} MB"
    return f"{size / 1024:,.1f} KB"
