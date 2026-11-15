from django.urls import path

from .raster_views import RasterAccessView, RasterClipView, RasterStatsView
from .views import AssetDataView, AssetDetailView, AssetSummaryView

app_name = "map"

urlpatterns = [
    path("assets/<uuid:asset_id>", AssetDetailView.as_view(), name="asset-detail"),
    path("assets/<uuid:asset_id>/data", AssetDataView.as_view(), name="asset-data"),
    path("assets/<uuid:asset_id>/summary", AssetSummaryView.as_view(), name="asset-summary"),
    path(
        "assets/<uuid:asset_id>/raster-access",
        RasterAccessView.as_view(),
        name="asset-raster-access",
    ),
    path(
        "assets/<uuid:asset_id>/raster-stats",
        RasterStatsView.as_view(),
        name="asset-raster-stats",
    ),
    path("assets/<uuid:asset_id>/clip.tif", RasterClipView.as_view(), name="asset-raster-clip"),
]
