"""The Map API: catalog reads, plus the lake for a vector asset's features."""

import logging
from itertools import groupby

from django.conf import settings
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


class AssetDataView(APIView):
    """One vector asset's features, read from the lake.

    Vector only, and the endpoint says so rather than inferring it: `assets`
    holds every modality and the lake read only makes sense for GeoParquet
    (docs/adr/008). Other modalities get their own endpoints.
    """

    @extend_schema(
        parameters=[AssetDataQuerySerializer],
        responses={
            200: AssetDataSerializer,
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
        try:
            data = lake.read_vector_features(
                uri,
                limit=asked.get("limit", settings.LAKE_PAGE_SIZE),
                bbox=area.envelope if area else asked.get("bbox"),
                area=area.wkt if area else None,
                cursor=asked.get("cursor"),
            )
        except lake.LakeUnavailable as exc:
            raise LakeUnreachable() from exc
        except lake.LakeReadError as exc:
            raise LakeFailed() from exc

        return Response(AssetDataSerializer({"asset_id": asset_id, **data}).data)
