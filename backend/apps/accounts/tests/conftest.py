import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.accounts.models import Role, UserProfile

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def api() -> APIClient:
    return APIClient()


def _make(username: str, role: str | None) -> User:
    user = User.objects.create_user(username=username, password=PASSWORD)
    if role is not None:
        UserProfile.objects.create(user=user, role=role)
    return user


@pytest.fixture
def viewer(db) -> User:
    return _make("viewer-user", Role.VIEWER)


@pytest.fixture
def admin_user(db) -> User:
    return _make("admin-user", Role.ADMIN)


@pytest.fixture
def profileless(db) -> User:
    """A user with no profile row at all — the HLR-008 case."""
    return _make("no-profile-user", None)


@pytest.fixture
def signed_in(api, viewer):
    """An API client carrying a live session for `viewer`."""
    response = api.post(
        "/api/auth/login",
        {"username": viewer.username, "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api
