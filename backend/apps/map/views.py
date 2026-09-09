from itertools import groupby

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog
from .serializers import AssetDetailSerializer, AssetsAtPointSerializer


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

        rows = catalog.assets_covering_point(
            point.validated_data["lon"], point.validated_data["lat"]
        )

        # catalog orders by data type, so grouping needs no second sort. A point
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
        detail = catalog.asset_detail(asset_id)
        if detail is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(AssetDetailSerializer(detail).data)
