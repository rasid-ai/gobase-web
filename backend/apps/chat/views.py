"""The chat gateway: the SPA's Ask endpoints, passed on to the agent.

`apps/chat` runs no agent loop and calls no model (docs/adr/021). It checks who
is asking, checks what they sent, and forwards it to `gobase-agent` with the
user's id; then it relays the answer. It stores nothing: chat history lives in
the agent's sessions bucket, and `portal` holds none of it (docs/adr/023).

A failure is never a 500, because the portal itself is fine:

- a blank `AGENT_URL` is 503 before any call, as with `GODOC_URL`;
- an agent that cannot be reached, or is not ready, is 503;
- an agent that refuses, or answers something that does not fit the
  contract, is 502;
- once an answer has started streaming, a failure can no longer be a status.
  It becomes a last `error` event with `incomplete: true`, so a cut-off
  answer is never shown as whole.

Nothing here logs chat content: not the question, not the answer, and not
the agent's error text. Only exception types and statuses (CLAUDE.md).
"""

import json
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, MethodNotAllowed, NotAuthenticated, NotFound
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import agent, sse
from .serializers import (
    EVENT_SERIALIZERS,
    AskTurnRequestSerializer,
    ChatSessionDetailSerializer,
    ChatSessionListSerializer,
    ChatTurnEventSchema,
    agent_context,
)

logger = logging.getLogger(__name__)

# What the SPA shows when an answer stopped and the agent could not say why.
CUT_OFF = "The answer was cut off."


class AskUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Ask is unavailable"


class AskFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The Ask service returned an error"


_FAILURES = {
    502: OpenApiResponse(description="The agent refused, or answered outside the contract."),
    503: OpenApiResponse(description="The agent is unreachable, or no AGENT_URL is set."),
}


def _require_agent() -> None:
    # Checked before the call: with no URL every request would spend a round
    # trip to be told the same thing. The detail differs from the unreachable
    # one so the log tells the two apart.
    if not settings.AGENT_URL:
        logger.warning("Ask asked for, but no agent URL is configured")
        raise AskUnavailable("Ask is not configured")


def _ask(call, *args):
    """Call the agent, turning its failures into this API's statuses."""
    try:
        return call(*args)
    except agent.AgentUnavailable as exc:
        logger.warning("Agent unreachable: %s", exc)
        raise AskUnavailable() from exc
    except agent.AgentNotFound as exc:
        raise NotFound("No such chat session") from exc
    except agent.AgentError as exc:
        logger.warning("Agent error: %s", exc)
        raise AskFailed() from exc


def _checked(serializer_class, payload: dict) -> dict:
    """The agent's answer cut to the contract, or a 502 if it does not fit."""
    serializer = serializer_class(data=payload)
    if not serializer.is_valid():
        # The fields that failed, never their values: those are chat content.
        logger.warning(
            "Agent answer did not fit %s: %s", serializer_class.__name__, sorted(serializer.errors)
        )
        raise AskFailed()
    return serializer.data


def _user_id(user) -> str:
    """The id the agent keeps this user's sessions under (docs/adr/023)."""
    return str(user.pk)


class SessionListView(APIView):
    @extend_schema(
        responses={200: ChatSessionListSerializer, **_FAILURES},
        operation_id="chat_session_list",
        summary="The signed-in user's chat sessions, newest first",
        tags=["chat"],
    )
    def get(self, request):
        _require_agent()
        payload = _ask(agent.list_sessions, _user_id(request.user))
        return Response(_checked(ChatSessionListSerializer, payload))


class SessionDetailView(APIView):
    @extend_schema(
        responses={
            200: ChatSessionDetailSerializer,
            404: OpenApiResponse(description="The signed-in user has no such session."),
            **_FAILURES,
        },
        operation_id="chat_session_retrieve",
        summary="One chat session with every question and answer, oldest first",
        tags=["chat"],
    )
    def get(self, request, session_id):
        _require_agent()
        payload = _ask(agent.read_session, _user_id(request.user), str(session_id))
        return Response(_checked(ChatSessionDetailSerializer, payload))

    @extend_schema(
        responses={
            204: OpenApiResponse(description="Deleted."),
            404: OpenApiResponse(description="The signed-in user has no such session."),
            **_FAILURES,
        },
        operation_id="chat_session_delete",
        summary="Delete one chat session",
        tags=["chat"],
    )
    def delete(self, request, session_id):
        _require_agent()
        _ask(agent.delete_session, _user_id(request.user), str(session_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class TurnView(APIView):
    """The schema of one turn. The endpoint itself is `relay_turn`, below.

    DRF's views are synchronous, and the relay must not be: it waits on the
    agent for the whole answer, while the agent's own tool calls come back into
    this backend and need workers of their own (docs/adr/021, docs/adr/022).
    `relay_turn` is a plain async Django view; it names this class as its
    `cls` so that drf-spectacular finds it and `openapi.yaml` carries it.
    """

    # JSON only, as `relay_turn` parses it; the schema lists these.
    parser_classes = [JSONParser]

    @extend_schema(
        request=AskTurnRequestSerializer,
        responses={
            (200, "text/event-stream"): OpenApiResponse(
                response=ChatTurnEventSchema,
                description=(
                    "Server-sent events. Each `data:` line is one ChatTurnEvent as JSON. "
                    "The last is `done` for a whole answer or `error` for one that stopped "
                    "part-way; `step`, `text` and `reference` come before it, in any number."
                ),
            ),
            400: OpenApiResponse(description="The question or the map context is not valid."),
            **_FAILURES,
        },
        operation_id="chat_turn_create",
        summary="Ask one question in a session, and stream the answer",
        description=(
            "An unknown session id starts a new session, so the client names a new "
            "session by choosing a fresh UUID."
        ),
        tags=["chat"],
    )
    def post(self, request, session_id):
        # Never routed: urls.py sends this path to `relay_turn`.
        raise NotImplementedError


def _problem(exc: APIException) -> JsonResponse:
    """An APIException as DRF's own handler would have answered it."""
    detail = exc.detail
    data = detail if isinstance(detail, (dict, list)) else {"detail": detail}
    response = JsonResponse(data, status=exc.status_code, safe=False)
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        response["WWW-Authenticate"] = 'Bearer realm="api"'
    return response


def _admit(request) -> tuple[str, dict] | JsonResponse:
    """Who is asking and what, checked exactly as DRF checks every other view.

    Synchronous on purpose: finding the user is a database read. It runs in a
    thread for the moment it takes, never for the length of the answer.
    """
    wrapped = Request(request, parsers=[JSONParser()], authenticators=[JWTAuthentication()])
    try:
        if not wrapped.user or not wrapped.user.is_authenticated:
            raise NotAuthenticated()
        turn = AskTurnRequestSerializer(data=wrapped.data)
        turn.is_valid(raise_exception=True)
    except APIException as exc:
        return _problem(exc)

    data = turn.validated_data
    body = {"prompt": data["prompt"], "context": agent_context(data.get("context", {}))}
    return _user_id(wrapped.user), body


@csrf_exempt  # Authenticated by a bearer header, never by a cookie.
async def relay_turn(request, session_id):
    if request.method != "POST":
        return _problem(MethodNotAllowed(request.method))
    admitted = await sync_to_async(_admit)(request)
    if isinstance(admitted, JsonResponse):
        return admitted
    user_id, body = admitted

    if not settings.AGENT_URL:
        logger.warning("Ask asked for, but no agent URL is configured")
        return _problem(AskUnavailable("Ask is not configured"))

    try:
        turn = await agent.start_turn(user_id, str(session_id), body)
    except agent.AgentUnavailable as exc:
        logger.warning("Agent unreachable: %s", exc)
        return _problem(AskUnavailable())
    except agent.AgentError as exc:
        logger.warning("Agent error: %s", exc)
        return _problem(AskFailed())

    response = StreamingHttpResponse(_relay(turn), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    # The host nginx buffers proxied responses by default, which would hold
    # the whole answer back until it finished.
    response["X-Accel-Buffering"] = "no"
    return response


relay_turn.cls = TurnView
relay_turn.initkwargs = {}


class _Malformed(Exception):
    """An agent event that does not fit the contract."""


def _event(name: str, data: str) -> dict | None:
    """One agent event in the SPA's terms; None for a kind this contract lacks.

    An unknown kind is skipped rather than fatal, so a newer agent can add one
    without breaking an older portal. A known kind that does not fit its shape
    ends the answer: the SPA must not render a half-understood event.
    """
    serializer_class = EVENT_SERIALIZERS.get(name)
    if serializer_class is None:
        return None
    try:
        payload = json.loads(data)
    except ValueError:
        raise _Malformed(f"{name}: no JSON") from None
    if not isinstance(payload, dict):
        raise _Malformed(f"{name}: not an object")

    # The agent sends a reference as the event's whole data; here it is one
    # field of the event, so every event is an object with `event` in it.
    shaped = {"event": name, "reference": payload} if name == "reference" else {**payload}
    shaped["event"] = name
    serializer = serializer_class(data=shaped)
    if not serializer.is_valid():
        raise _Malformed(f"{name}: {sorted(serializer.errors)}")
    return serializer.data


async def _relay(turn: agent.Turn):
    """The agent's events, checked one by one, then closed.

    Ends after `done` or `error`. If the agent's stream ends without either,
    breaks, goes silent, or sends something malformed, the SPA gets an `error`
    event of its own, so it never has to guess whether an answer is whole.

    A browser that goes away cancels this generator (Django's ASGI handler does
    that on disconnect), and `finally` closes the agent's stream with it.
    """
    ended = False
    try:
        async for name, data in turn.events():
            event = _event(name, data)
            if event is None:
                continue
            yield sse.frame(event)
            if event["event"] in ("done", "error"):
                ended = True
                break
    except agent.StreamBroken as exc:
        logger.warning("Agent stream broke: %s", exc)
    except _Malformed as exc:
        logger.warning("Agent sent an event outside the contract: %s", exc)
    finally:
        await turn.close()

    if not ended:
        yield sse.frame({"event": "error", "message": CUT_OFF, "incomplete": True})
