from django.urls import path

from .views import PlaceSearchView

app_name = "places"

urlpatterns = [
    path("search", PlaceSearchView.as_view(), name="search"),
]
