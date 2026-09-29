from django.urls import path

from .views import AssetListView, DatasetListView

app_name = "catalog"

urlpatterns = [
    path("assets", AssetListView.as_view(), name="asset-list"),
    path("datasets", DatasetListView.as_view(), name="dataset-list"),
]
