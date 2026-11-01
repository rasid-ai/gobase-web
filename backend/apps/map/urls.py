from django.urls import path

from .raster_views import RasterAccessView
from .views import AssetDataView, AssetDetailView

app_name = "map"

urlpatterns = [
    path("assets/<uuid:asset_id>", AssetDetailView.as_view(), name="asset-detail"),
    path("assets/<uuid:asset_id>/data", AssetDataView.as_view(), name="asset-data"),
    path(
        "assets/<uuid:asset_id>/raster-access",
        RasterAccessView.as_view(),
        name="asset-raster-access",
    ),
]
