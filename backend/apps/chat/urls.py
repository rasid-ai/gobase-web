from django.urls import path

from .views import SessionDetailView, SessionListView, relay_turn

app_name = "chat"

urlpatterns = [
    path("sessions", SessionListView.as_view(), name="sessions"),
    path("sessions/<uuid:session_id>", SessionDetailView.as_view(), name="session"),
    # An async view, not a DRF one: see TurnView in views.py.
    path("sessions/<uuid:session_id>/turns", relay_turn, name="turns"),
]
