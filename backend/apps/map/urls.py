from django.urls import path

from .views import AssetDataView, AssetDetailView, AssetsAtPointView

app_name = "map"

urlpatterns = [
    path("assets", AssetsAtPointView.as_view(), name="assets-at-point"),
    path("assets/<uuid:asset_id>", AssetDetailView.as_view(), name="asset-detail"),
    path("assets/<uuid:asset_id>/data", AssetDataView.as_view(), name="asset-data"),
]
