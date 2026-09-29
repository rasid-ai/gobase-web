"""
Tests for the deploy health check (config/health.py).

The endpoint exists for infra/deploy.sh rather than for anything a user does,
and is covered because a deploy that cannot trust its health check is worse
than one with no check at all.
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
