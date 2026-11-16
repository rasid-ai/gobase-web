"""The only module that speaks to the Ask agent, `gobase-agent`.

The agent is a separate service deployed alone, and this backend is its only
caller (docs/adr/023). Every call presents `AGENT_SERVICE_TOKEN` and names the
signed-in user, whose id is the prefix the agent keeps that user's sessions
under (docs/adr/025). Everything above this module speaks in portal terms; the
agent's paths, headers and status codes stay here.
context/integrations/agent.md has the contract.

Failures come out as three exceptions, the same split GoDoc's client makes:
`AgentUnavailable` (not reached, or not ready: the view answers 503),
`AgentError` (it answered, and refused: 502), and `AgentNotFound` (no such
session for this user: 404). None of their messages quote a URL, the token or
any chat content (CLAUDE.md).
"""

from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
from django.conf import settings

from . import sse

# The transport every client uses. None is httpx's own; the tests put an
# `httpx.MockTransport` here, which serves both the sync and the async client.
TRANSPORT: httpx.MockTransport | None = None

# Statuses that mean the agent, or a proxy in front of it, is not ready —
# the same as not reaching it at all.
_NOT_READY = {502, 503, 504}


class AgentUnavailable(Exception):
    """The agent could not be reached, or said it is not ready."""


class AgentError(Exception):
    """The agent answered, but refused the request or answered nonsense."""


class AgentNotFound(Exception):
    """The agent has no such session under this user."""


class StreamBroken(Exception):
    """A streamed answer stopped part-way: the connection failed or went silent."""


def _url(user_id: str, session_id: str | None = None, *rest: str) -> str:
    # Both ids are quoted although neither can hold a `/` today (a user's
    # primary key and a UUID): they become S3 key parts on the far side.
    path = f"/v1/users/{quote(user_id, safe='')}/sessions"
    if session_id is not None:
        path += f"/{quote(session_id, safe='')}"
    for part in rest:
        path += f"/{part}"
    return settings.AGENT_URL.rstrip("/") + path


def _headers() -> dict[str, str]:
    # No token, no header. "Bearer " with nothing after it is not a legal
    # header value: httpx refuses to send it, and every call would look like
    # an unreachable agent (503). Without the header, an agent that wants a
    # token answers 401, which shows as the 502 it really is.
    token = settings.AGENT_SERVICE_TOKEN.strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _failure(status_code: int) -> Exception:
    if status_code in _NOT_READY:
        return AgentUnavailable(f"HTTP {status_code}")
    if status_code == 404:
        return AgentNotFound(f"HTTP {status_code}")
    return AgentError(f"HTTP {status_code}")


def _call(method: str, url: str) -> httpx.Response:
    """One short call, with its failures turned into this module's exceptions."""
    try:
        with httpx.Client(transport=TRANSPORT, timeout=settings.AGENT_TIMEOUT_SECONDS) as client:
            response = client.request(method, url, headers=_headers())
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        # The type, not the message: an httpx message can quote the request.
        raise AgentUnavailable(type(exc).__name__) from exc
    if response.status_code >= 400:
        raise _failure(response.status_code)
    return response


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise AgentError(f"HTTP {response.status_code} and no JSON") from None
    if not isinstance(payload, dict):
        raise AgentError("The answer is not a JSON object")
    return payload


def list_sessions(user_id: str) -> dict:
    """The user's sessions, newest first, as the agent sent them."""
    return _json(_call("GET", _url(user_id)))


def read_session(user_id: str, session_id: str) -> dict:
    """One of the user's sessions with its turns, as the agent sent it."""
    return _json(_call("GET", _url(user_id, session_id)))


def delete_session(user_id: str, session_id: str) -> None:
    _call("DELETE", _url(user_id, session_id))


class Turn:
    """An answer the agent is streaming. Read `events()`, then `close()`."""

    def __init__(self, client: httpx.AsyncClient, response: httpx.Response):
        self._client = client
        self._response = response

    async def events(self) -> AsyncIterator[tuple[str, str]]:
        """Each event as `(name, data)`, until the agent ends the stream.

        A connection that fails, or stays silent longer than
        `AGENT_STREAM_TIMEOUT_SECONDS`, raises `StreamBroken`.
        """
        try:
            async for event in sse.parse(self._response.aiter_text()):
                yield event
        except (httpx.TimeoutException, httpx.TransportError, httpx.StreamError) as exc:
            raise StreamBroken(type(exc).__name__) from exc

    async def close(self) -> None:
        await self._response.aclose()
        await self._client.aclose()


async def start_turn(user_id: str, session_id: str, body: dict) -> Turn:
    """Ask one question, and return once the agent has accepted it.

    Waits for the agent's status line and no further, so a refusal is still an
    HTTP status for the SPA — the question stays in its box and nothing has
    streamed yet. An unknown `session_id` starts a new session on the agent.
    """
    client = httpx.AsyncClient(
        transport=TRANSPORT,
        # `read` is the gap allowed between two pieces of the stream, not the
        # whole answer, so a long answer that keeps sending is never cut.
        timeout=httpx.Timeout(
            settings.AGENT_STREAM_TIMEOUT_SECONDS, connect=settings.AGENT_TIMEOUT_SECONDS
        ),
    )
    request = client.build_request(
        "POST",
        _url(user_id, session_id, "turns"),
        json=body,
        headers={**_headers(), "Accept": "text/event-stream"},
    )
    try:
        response = await client.send(request, stream=True)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        await client.aclose()
        raise AgentUnavailable(type(exc).__name__) from exc

    if response.status_code != 200:
        await response.aclose()
        await client.aclose()
        failure = _failure(response.status_code)
        # A turn has no "not found": an unknown session is a new one.
        raise AgentError(str(failure)) if isinstance(failure, AgentNotFound) else failure

    return Turn(client, response)
