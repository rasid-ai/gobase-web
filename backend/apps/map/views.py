"""The Map API: catalog reads, plus the lake for a vector asset's features."""

import gzip
import hashlib
import logging
import re
from itertools import groupby

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.cache import patch_vary_headers
from django.utils.http import parse_etags
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import kb
from apps.catalog.serializers import AreaField

from . import lake
from .serializers import (
    AssetDataQuerySerializer,
    AssetDataSerializer,
    AssetDetailSerializer,
    AssetsAtPointSerializer,
)

logger = logging.getLogger(__name__)


class LakeUnreachable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The data lake is unreachable"


class LakeFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The data lake returned an error"


class _PlaceSerializer(serializers.Serializer):
    """Where to look: a clicked point or a drawn area, exactly one of them.

    Both are optional to the contract and one is required here, because
    OpenAPI has no plain way to say "either this pair or that one" that the
    generated client would honour.
    """

    lon = serializers.FloatField(
        required=False,
        min_value=-180,
        max_value=180,
        help_text="Longitude, WGS 84. Sent with `lat`, never with `area`.",
    )
    lat = serializers.FloatField(
        required=False,
        min_value=-90,
        max_value=90,
        help_text="Latitude, WGS 84. Sent with `lon`, never with `area`.",
    )
    area = AreaField(
        required=False,
        help_text=(
            "A drawn polygon as WKT, POLYGON((lon lat, ...)), SRID 4326, at most "
            "100 corners and not crossing itself. Sent instead of lon and lat."
        ),
    )

    def validate(self, attrs):
        has_point = "lon" in attrs or "lat" in attrs
        if "area" in attrs:
            if has_point:
                raise serializers.ValidationError("Send a point or an area, not both.")
            return attrs
        if "lon" not in attrs or "lat" not in attrs:
            raise serializers.ValidationError("Send a point (lon and lat) or an area.")
        return attrs


class AssetsAtPointView(APIView):
    """List the catalog assets covering a clicked point or overlapping a drawn area.

    One endpoint for both because they are one question — "what data is about
    this place" — asked with two geometries, and the answer has the same shape
    either way (docs/adr/014). The operation keeps its original id so the
    generated client's hook keeps its name.
    """

    @extend_schema(
        parameters=[_PlaceSerializer],
        responses={
            200: AssetsAtPointSerializer,
            400: OpenApiResponse(
                description="No place given, both given, or a point or area that cannot be read."
            ),
        },
        operation_id="map_assets_at_point",
        summary="Assets covering a point or a drawn area",
        tags=["map"],
    )
    def get(self, request):
        place = _PlaceSerializer(data=request.query_params)
        place.is_valid(raise_exception=True)
        asked = place.validated_data

        if "area" in asked:
            rows = kb.assets_overlapping_area(asked["area"].wkt)
        else:
            rows = kb.assets_covering_point(asked["lon"], asked["lat"])

        # kb orders by data type, so grouping needs no second sort. A point
        # nothing covers yields no groups — an empty answer, not an error.
        groups = [
            {"data_type": data_type, "assets": list(assets)}
            for data_type, assets in groupby(rows, key=lambda row: row["modality"])
        ]
        return Response(AssetsAtPointSerializer({"groups": groups}).data)


class AssetDetailView(APIView):
    """One asset's metadata and footprint."""

    @extend_schema(
        responses={
            200: AssetDetailSerializer,
            404: OpenApiResponse(description="No active asset with that id."),
        },
        operation_id="map_asset_detail",
        summary="Asset metadata and footprint",
        tags=["map"],
    )
    def get(self, request, asset_id):
        detail = kb.asset_detail(asset_id)
        if detail is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(AssetDetailSerializer(detail).data)


# Bump whenever the same request could now get a different body: a change to
# the response shape, to how the lake read filters, or to how a value is
# written. Every ETag carries it, so bumping it invalidates every copy any
# browser holds — which is the only way to, since the URLs do not change.
FEATURES_FORMAT = 1


def _features_etag(asset_id, limit, bbox, area, cursor) -> str:
    """The ETag for one page of one asset's features, computed without reading it.

    Possible only because assets are content-addressed: changed content gets a
    new asset_id and the old one is superseded (context/integrations/kb.md,
    `content_hash`). So the id plus the request plus the format version
    decide the body completely, and a revalidation can be answered before the
    lake is touched.
    """
    key = f"{FEATURES_FORMAT}|{asset_id}|{limit}|{bbox}|{area}|{cursor}"
    return f'W/"{hashlib.sha256(key.encode()).hexdigest()[:32]}"'


class AssetDataView(APIView):
    """One vector asset's features, read from the lake.

    Vector only, and the endpoint says so rather than inferring it: `assets`
    holds every modality and the lake read only makes sense for GeoParquet
    (docs/adr/008). Other modalities get their own endpoints.

    The one endpoint that writes its own body instead of going through DRF's
    renderer, and the one that is compressed and cached (docs/adr/015). A page
    is megabytes of GeoJSON that DuckDB has already written, so rendering it
    again would only parse and re-serialise it. `AssetDataSerializer` still
    declares its shape to the contract.

    Compressed here, not site-wide: Django's middleware also compresses
    streaming responses, which would hold back the server-sent events the Ask
    slice will use, and compressing only this keeps it away from any response
    that carries a secret (BREACH). See `_compressed` for why not Django's own
    `gzip_page` either.
    """

    @extend_schema(
        parameters=[AssetDataQuerySerializer],
        responses={
            200: AssetDataSerializer,
            304: OpenApiResponse(
                description=(
                    "The ETag sent in If-None-Match still matches; use the copy already held. "
                    "A browser handles this itself and hands the client its cached 200."
                )
            ),
            400: OpenApiResponse(
                description="An unreadable bbox, area, cursor or limit, or both bbox and area."
            ),
            404: OpenApiResponse(description="No active vector asset with that id."),
            502: OpenApiResponse(description="The file could not be read."),
            503: OpenApiResponse(description="The lake could not be reached."),
        },
        operation_id="map_asset_data",
        summary="Vector asset features",
        tags=["map"],
    )
    def get(self, request, asset_id):
        query = AssetDataQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        asked = query.validated_data

        # The lake URI is resolved here and never leaves the server: the client
        # gets features, not a path into the bucket.
        uri = kb.vector_source_uri(asset_id)
        if uri is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # A drawn area reaches the lake as its envelope plus the polygon: the
        # envelope prunes, the polygon decides.
        area = asked.get("area")
        limit = asked.get("limit", settings.LAKE_PAGE_SIZE)
        bbox = area.envelope if area else asked.get("bbox")
        wkt = area.wkt if area else None
        cursor = asked.get("cursor")

        # Checked after the catalog, not before: a superseded asset must answer
        # 404, not tell the browser its old copy is still good.
        etag = _features_etag(asset_id, limit, bbox, wkt, cursor)
        held = parse_etags(request.headers.get("If-None-Match", ""))
        if etag in held or "*" in held:
            return _cacheable(HttpResponseNotModified(), etag)

        try:
            data = lake.read_vector_features(uri, limit=limit, bbox=bbox, area=wkt, cursor=cursor)
        except lake.LakeUnavailable as exc:
            raise LakeUnreachable() from exc
        except lake.LakeReadError as exc:
            raise LakeFailed() from exc

        # Written, not rendered: the features are already JSON text. The other
        # values are a UUID from the URL and two integers, so nothing here
        # needs escaping.
        next_cursor = "null" if data["next_cursor"] is None else int(data["next_cursor"])
        body = (
            f'{{"asset_id":"{asset_id}","count":{int(data["count"])},'
            f'"next_cursor":{next_cursor},"features":{data["features_json"]}}}'
        )
        response = HttpResponse(body, content_type="application/json")
        return _compressed(request, _cacheable(response, etag))


_ACCEPTS_GZIP = re.compile(r"\bgzip\b")


def _compressed(request, response):
    """Gzip a features page at level 1, for a client that accepts it.

    Not Django's `gzip_page`, which compresses at level 6 and offers no way to
    change it. On a 10,000-building page level 6 took 315 ms — more than
    building the page did (188 ms) — for 1.17 MB; level 1 took 90 ms for
    1.29 MB. Ten percent more bytes for a third of the time is the right trade
    for a response built on every pan.

    No BREACH padding, unlike Django's: the body is features read from the
    lake and carries nothing secret for an attacker to recover.
    """
    patch_vary_headers(response, ("Accept-Encoding",))
    if not _ACCEPTS_GZIP.search(request.headers.get("Accept-Encoding", "")):
        return response
    response.content = gzip.compress(response.content, compresslevel=1, mtime=0)
    response["Content-Encoding"] = "gzip"
    response["Content-Length"] = str(len(response.content))
    return response


def _cacheable(response, etag: str):
    """Mark a features response as one the browser may keep and must revalidate.

    `no-cache` is not "do not cache": the browser stores the page and asks
    before each reuse, sending the ETag back, and a still-matching one costs a
    catalog lookup and an empty 304 rather than a lake read. Not a long
    max-age: that would keep serving a stale shape after a deploy changes
    one, because the URL would not change. And `private`, because the request
    carries a token and no shared cache should hold the answer.
    """
    response["ETag"] = etag
    response["Cache-Control"] = "private, no-cache"
    return response
