"""Fixtures for the Catalog tests.

`kb` is mirrored onto `default` in tests (context/integrations/kb.md), so there
is no real knowledge base here and nothing to seed. The browse query is faked
at its own boundary — `kb.asset_list` — and what the tests assert is the
arguments the view passes down and the shape the serializer sends back.
"""

import pytest
from django.contrib.auth.models import User

from apps.accounts.models import Role, UserProfile

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def as_viewer(api, db):
    user = User.objects.create_user(username="catalog-viewer", password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    response = api.post(
        "/api/auth/login",
        {"username": "catalog-viewer", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api


@pytest.fixture
def captured(monkeypatch):
    """Replace the browse query and record what the view asked it for."""
    from apps.catalog import kb

    calls = {}

    def fake(**kwargs):
        calls.update(kwargs)
        return {"count": 0, "results": [], "data_type_counts": []}

    monkeypatch.setattr(kb, "asset_list", fake)
    return calls
