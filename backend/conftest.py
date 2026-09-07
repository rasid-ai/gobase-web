"""Fixtures shared by every test package (apps/ and config/)."""

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api() -> APIClient:
    return APIClient()
