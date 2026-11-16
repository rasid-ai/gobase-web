"""Fixtures for the chat tests.

The agent is faked at its transport: `agent.TRANSPORT` takes an
`httpx.MockTransport`, which serves the sync client (sessions) and the async
one (a turn) alike. So everything above the wire runs for real — the URLs,
the headers, the status mapping, the SSE reading and the relay — and every
test states what the agent answers.

Nothing is stored, so there is nothing to seed beyond a signed-in user.
"""

import json

import httpx
import pytest
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Role, UserProfile
from apps.chat import agent

AGENT_URL = "http://agent:8010"
TOKEN = "not-a-real-token"
SESSION = "6f1c2a8e-4b7d-4c1e-9a3f-2d5b8e7c1a90"
ASSET = "b9bb3097-9feb-4805-b4b3-aed8d25fbada"


@pytest.fixture
def configured(settings):
    settings.AGENT_URL = AGENT_URL
    settings.AGENT_SERVICE_TOKEN = TOKEN


@pytest.fixture
def user(db):
    user = User.objects.create_user(username="ask-viewer", password="unused-in-these-tests")
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    return user


@pytest.fixture
def bearer(user) -> str:
    return f"Bearer {AccessToken.for_user(user)}"


@pytest.fixture
def as_viewer(api, bearer):
    api.credentials(HTTP_AUTHORIZATION=bearer)
    return api


class FakeAgent:
    """Answers each request with what the test queued, and records the request."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.answer = httpx.Response(200, json={})

    def handler(self, request: httpx.Request):
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def body(self) -> dict:
        return json.loads(self.last.content)


@pytest.fixture
def fake_agent(monkeypatch, configured):
    fake = FakeAgent()
    monkeypatch.setattr(agent, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


def session_row(**overrides):
    return {
        "session_id": SESSION,
        "title": "What does the airport report say about security?",
        "created_at": "2026-11-09T08:00:00Z",
        "updated_at": "2026-11-09T08:01:30Z",
        **overrides,
    }
