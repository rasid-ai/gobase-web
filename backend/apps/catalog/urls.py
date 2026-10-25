from django.urls import path

from .views import AssetListView, DatasetListView, DocumentPdfView

app_name = "catalog"

urlpatterns = [
    path("assets", AssetListView.as_view(), name="asset-list"),
    path("assets/<uuid:asset_id>/pdf", DocumentPdfView.as_view(), name="document-pdf"),
    path("datasets", DatasetListView.as_view(), name="dataset-list"),
]
