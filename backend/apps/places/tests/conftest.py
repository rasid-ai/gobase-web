"""Fixtures for the Places tests.

Nothing is stored and nothing is read from a database, so there is nothing to
seed. The geocoder is faked at one of two boundaries: `esri.httpx.post` when the
test is about the request the portal sends, and `views.esri.find_places` when it
is about the answer the portal gives back.
"""

import pytest
from django.contrib.auth.models import User

from apps.accounts.models import Role, UserProfile

PASSWORD = "correct-horse-battery-staple"

# Every test that reaches the geocoder needs a key set, or the view short
# circuits to 503 before the fake is ever called.
A_KEY = "not-a-real-key"


@pytest.fixture
def as_viewer(api, db, settings):
    settings.ESRI_API_KEY = A_KEY
    user = User.objects.create_user(username="places-viewer", password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    response = api.post(
        "/api/auth/login",
        {"username": "places-viewer", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api


def candidate(**overrides):
    """One candidate as the geocoder sends it, before the portal reshapes it."""
    return {
        "address": "Beirut, Lebanon",
        "location": {"x": 35.5018, "y": 33.8938},
        "score": 100,
        "extent": {"xmin": 35.4, "ymin": 33.8, "xmax": 35.6, "ymax": 34.0},
        **overrides,
    }
