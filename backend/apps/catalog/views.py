"""The Catalog API: browsing everything the knowledge base holds."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from . import kb
from .serializers import (
    AssetListQuerySerializer,
    AssetListSerializer,
    DatasetListQuerySerializer,
    DatasetListSerializer,
)


class AssetListView(APIView):
    """One page of the catalog, filtered and sorted.

    Both pages browse through here. The Assets page narrows it to a searched
    place, and the map's panel to a clicked point or a drawn area — one
    question with three geometries, and one answer to it, so the search, the
    datasets and the counts cannot differ between the two (docs/adr/016).
    """

    @extend_schema(
        parameters=[AssetListQuerySerializer],
        responses={
            200: AssetListSerializer,
            400: OpenApiResponse(
                description="A filter that cannot be read, half a point, or more than one place."
            ),
        },
        operation_id="catalog_asset_list",
        summary="Browse the asset catalog",
        tags=["catalog"],
    )
    def get(self, request):
        query = AssetListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        page = kb.asset_list(
            # An absent filter and an empty one mean the same thing here: no
            # restriction. `q=` is what the search box sends once it is cleared.
            q=filters.get("q") or None,
            data_types=filters.get("data_type") or None,
            dataset=filters.get("dataset") or None,
            **query.place(),
            ingested_after=filters.get("ingested_after"),
            ingested_before=filters.get("ingested_before"),
            sort=filters["sort"],
            limit=filters["limit"],
            offset=filters["offset"],
        )
        return Response(AssetListSerializer(page).data)


class DatasetListView(APIView):
    """The datasets holding matching assets, and how many of each type.

    The first step of browsing by dataset, on both pages: pick one here, then
    list its assets with `dataset=` on the asset list, sending the same place
    and window so the count shown here is the count found there.
    """

    @extend_schema(
        parameters=[DatasetListQuerySerializer],
        responses={
            200: DatasetListSerializer,
            400: OpenApiResponse(
                description="A filter that cannot be read, half a point, or more than one place."
            ),
        },
        operation_id="catalog_dataset_list",
        summary="Datasets in the catalog",
        tags=["catalog"],
    )
    def get(self, request):
        query = DatasetListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data

        datasets = kb.dataset_list(
            q=filters.get("q") or None,
            **query.place(),
            ingested_after=filters.get("ingested_after"),
            ingested_before=filters.get("ingested_before"),
        )
        return Response(DatasetListSerializer({"results": datasets}).data)
