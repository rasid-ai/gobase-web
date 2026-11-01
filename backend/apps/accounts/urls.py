from django.urls import path

from .api_key_views import ApiKeyIssueView
from .views import ChangePasswordView, LoginView, LogoutView, MeView, RefreshView

app_name = "accounts"

urlpatterns = [
    path("api-keys", ApiKeyIssueView.as_view(), name="api-keys"),
    path("login", LoginView.as_view(), name="login"),
    path("refresh", RefreshView.as_view(), name="refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("me", MeView.as_view(), name="me"),
    path("change-password", ChangePasswordView.as_view(), name="change-password"),
]
