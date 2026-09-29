from django.urls import path

from .views import RunDetailView, RunListView, RunLogsView, RunTriggerView

app_name = "runs"

urlpatterns = [
    path("", RunListView.as_view(), name="list"),
    path("trigger", RunTriggerView.as_view(), name="trigger"),
    path("<uuid:run_id>", RunDetailView.as_view(), name="detail"),
    path("<uuid:run_id>/logs", RunLogsView.as_view(), name="logs"),
]
