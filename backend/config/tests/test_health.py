"""
Tests for the deploy health check (config/health.py).

No HLR id: the endpoint exists for infra/deploy.sh, not for a requirement in
specs/. It is still covered, because a deploy that cannot trust its gate is
worse than one with no gate at all.
"""

from unittest.mock import patch

import pytest
from django.db import DatabaseError

pytestmark = pytest.mark.django_db


def test_health_reports_ok_when_the_portal_database_answers(api):
    response = api.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_needs_no_authentication(api):
    """deploy.sh curls this with no credentials, and nginx must not gate it."""
    response = api.get("/api/health/")

    assert response.status_code == 200


def test_health_reports_503_when_the_portal_database_is_unreachable(api):
    with patch("config.health.connections") as connections:
        connections.__getitem__.return_value.cursor.side_effect = DatabaseError("down")
        response = api.get("/api/health/")

    assert response.status_code == 503
