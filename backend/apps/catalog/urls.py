from django.urls import path

from .views import AssetListView

app_name = "catalog"

urlpatterns = [
    path("assets", AssetListView.as_view(), name="asset-list"),
]
