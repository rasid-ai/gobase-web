"""The Catalog API: browsing everything the knowledge base holds."""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from . import kb
from .serializers import AssetListQuerySerializer, AssetListSerializer


class AssetListView(APIView):
    """One page of the catalog, filtered and sorted.

    Browsing is not a map feature, which is why this is its own app: the map's
    `/api/map/assets` already means "the assets covering this place" — a
    clicked point or a drawn area, one question asked with two geometries — and
    cannot carry a second, different question (docs/adr/010, docs/adr/014).
    """

    @extend_schema(
        parameters=[AssetListQuerySerializer],
        responses={200: AssetListSerializer},
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
            bbox=filters.get("bbox"),
            ingested_after=filters.get("ingested_after"),
            ingested_before=filters.get("ingested_before"),
            sort=filters["sort"],
            limit=filters["limit"],
            offset=filters["offset"],
        )
        return Response(AssetListSerializer(page).data)
