"""The Map API: catalog reads, plus the lake for a vector asset's features."""

import logging
from itertools import groupby

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import kb

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


class _PointSerializer(serializers.Serializer):
    """The clicked point, validated before it reaches the knowledge base."""

    lon = serializers.FloatField(min_value=-180, max_value=180)
    lat = serializers.FloatField(min_value=-90, max_value=90)


class AssetsAtPointView(APIView):
    """List the catalog assets whose coverage includes a point."""

    @extend_schema(
        parameters=[
            OpenApiParameter("lon", float, required=True, description="Longitude, WGS 84."),
            OpenApiParameter("lat", float, required=True, description="Latitude, WGS 84."),
            _PointSerializer,
        ],
        responses={
            200: AssetsAtPointSerializer,
            400: OpenApiResponse(description="Missing or out-of-range coordinates."),
        },
        operation_id="map_assets_at_point",
        summary="Assets covering a point",
        tags=["map"],
    )
    def get(self, request):
        point = _PointSerializer(data=request.query_params)
        point.is_valid(raise_exception=True)

        rows = kb.assets_covering_point(point.validated_data["lon"], point.validated_data["lat"])

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
            400: OpenApiResponse(description="An unreadable bbox, cursor or limit."),
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

        try:
            data = lake.read_vector_features(
                uri,
                limit=asked.get("limit", settings.LAKE_PAGE_SIZE),
                bbox=asked.get("bbox"),
                cursor=asked.get("cursor"),
            )
        except lake.LakeUnavailable as exc:
            raise LakeUnreachable() from exc
        except lake.LakeReadError as exc:
            raise LakeFailed() from exc

        return Response(AssetDataSerializer({"asset_id": asset_id, **data}).data)
