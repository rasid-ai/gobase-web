from django.urls import path

from .views import (
    AssetListView,
    DatasetListView,
    DocumentPageView,
    DocumentPdfView,
    PassagesView,
    SimilarAssetsView,
)

app_name = "catalog"

urlpatterns = [
    path("assets", AssetListView.as_view(), name="asset-list"),
    path("assets/similar", SimilarAssetsView.as_view(), name="similar-assets"),
    path("assets/<uuid:asset_id>/pdf", DocumentPdfView.as_view(), name="document-pdf"),
    path(
        "assets/<uuid:asset_id>/pages/<int:page>.png",
        DocumentPageView.as_view(),
        name="document-page",
    ),
    path("datasets", DatasetListView.as_view(), name="dataset-list"),
    # Not under assets/: the resource is passages, grouped by the document
    # they are in; assets/similar stays the card search (docs/adr/020).
    path("passages", PassagesView.as_view(), name="passages"),
]
