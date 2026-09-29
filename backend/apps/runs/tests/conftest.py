import pytest
from django.contrib.auth.models import User

from apps.accounts.models import Role, UserProfile

PASSWORD = "correct-horse-battery-staple"


def _signed_in(api, username: str, role: str):
    user = User.objects.create_user(username=username, password=PASSWORD)
    UserProfile.objects.create(user=user, role=role)
    response = api.post(
        "/api/auth/login", {"username": username, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api


@pytest.fixture
def as_viewer(api, db):
    return _signed_in(api, "runs-viewer", Role.VIEWER)


@pytest.fixture
def as_admin(api, db):
    return _signed_in(api, "runs-admin", Role.ADMIN)


def run_node(run_id="11111111-1111-1111-1111-111111111111", **overrides):
    """A Dagster run exactly as the GraphQL API returns one."""
    node = {
        "runId": run_id,
        "jobName": "weekly_pipeline",
        "status": "SUCCESS",
        "creationTime": 1757000000.0,
        "startTime": 1757000010.0,
        "endTime": 1757000070.0,
        "tags": [{"key": "dagster/schedule_name", "value": "weekly_schedule"}],
        "assetSelection": [{"path": ["bronze", "sync"]}],
        "stats": {
            "__typename": "RunStatsSnapshot",
            "stepsSucceeded": 5,
            "stepsFailed": 0,
            "materializations": 5,
        },
    }
    node.update(overrides)
    return node
