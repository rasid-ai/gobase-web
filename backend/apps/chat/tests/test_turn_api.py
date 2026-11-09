"""POST /api/chat/sessions/{id}/turns — one question, the answer streamed (docs/adr/023).

The view is async, so these tests go through Django's AsyncClient. Each one
runs the request to the end and reads the whole stream, then asserts what the
SPA received and what the agent was sent.
"""

import json

import httpx
from asgiref.sync import async_to_sync
from django.test import AsyncClient

from apps.accounts.models import ApiKey

from .conftest import AGENT_URL, ASSET, SESSION, TOKEN

URL = f"/api/chat/sessions/{SESSION}/turns"
AREA = "POLYGON((35.5 33.8, 35.6 33.8, 35.6 33.9, 35.5 33.8))"


def sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def stream(*parts: bytes, then: Exception | None = None):
    """An agent stream that sends `parts`, then breaks with `then` if given."""

    async def body():
        for part in parts:
            yield part
        if then is not None:
            raise then

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())


def ask(bearer: str | None, body: dict | None = None, method: str = "post"):
    """Send the request and read the stream; returns the response and its events."""

    async def go():
        client = AsyncClient()
        headers = {"Authorization": bearer} if bearer else {}
        if method == "post":
            response = await client.post(
                URL, data=body or {}, content_type="application/json", headers=headers
            )
        else:
            response = await client.get(URL, headers=headers)
        if not response.streaming:
            return response, None
        raw = b"".join([chunk async for chunk in response.streaming_content])
        return response, raw

    response, raw = async_to_sync(go)()
    if raw is None:
        return response, None
    events = []
    for block in raw.decode().split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return response, events


QUESTION = {"prompt": "What does the airport report say about security?"}
CUT_OFF = {"event": "error", "message": "The answer was cut off.", "incomplete": True}


def test_signing_in_is_required(db, fake_agent):
    response, _ = ask(None, QUESTION)

    assert response.status_code == 401
    assert fake_agent.requests == []


def test_a_bad_token_is_401(db, fake_agent):
    response, _ = ask("Bearer not-a-jwt", QUESTION)

    assert response.status_code == 401


def test_an_api_key_may_not_ask(user, fake_agent):
    # Keys only read (docs/adr/021), and asking is a POST: 403, as on every view.
    _, raw = ApiKey.issue(user, "a desktop client")

    response, _ = ask(f"Api-Key {raw}", QUESTION)

    assert response.status_code == 403
    assert fake_agent.requests == []


def test_only_post_asks(bearer, fake_agent):
    response, _ = ask(bearer, method="get")

    assert response.status_code == 405


def test_no_agent_url_is_503_before_any_call(bearer, fake_agent, settings):
    settings.AGENT_URL = ""

    response, _ = ask(bearer, QUESTION)

    assert response.status_code == 503
    assert fake_agent.requests == []


def test_an_empty_question_is_400(bearer, fake_agent):
    response, _ = ask(bearer, {"prompt": "   "})

    assert response.status_code == 400
    assert "prompt" in response.json()
    assert fake_agent.requests == []


def test_a_crossing_area_is_400(bearer, fake_agent):
    bowtie = "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"

    response, _ = ask(bearer, {**QUESTION, "context": {"area": bowtie}})

    assert response.status_code == 400
    assert fake_agent.requests == []


def test_an_inside_out_viewport_is_400(bearer, fake_agent):
    response, _ = ask(bearer, {**QUESTION, "context": {"viewport": [36, 34, 35, 33]}})

    assert response.status_code == 400


def test_the_question_and_map_context_go_to_the_agent_as_this_user(bearer, user, fake_agent):
    fake_agent.answer = stream(sse(("done", {"text": "", "references": []})))
    context = {
        "viewport": [35.4, 33.7, 35.7, 34.0],
        "point": [35.5, 33.85],
        "area": AREA,
        "asset_id": ASSET,
    }

    response, _ = ask(bearer, {**QUESTION, "context": context})

    assert response.status_code == 200
    request = fake_agent.last
    assert str(request.url) == f"{AGENT_URL}/v1/users/{user.pk}/sessions/{SESSION}/turns"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert fake_agent.body() == {"prompt": QUESTION["prompt"], "context": context}


def test_a_blank_service_token_sends_no_authorization_header(bearer, fake_agent, settings):
    # "Bearer " alone is an illegal header value that httpx refuses to send.
    settings.AGENT_SERVICE_TOKEN = ""
    fake_agent.answer = stream(sse(("done", {"text": "", "references": []})))

    response, _ = ask(bearer, QUESTION)

    assert response.status_code == 200
    assert "Authorization" not in fake_agent.last.headers


def test_absent_context_fields_are_left_out(bearer, fake_agent):
    fake_agent.answer = stream(sse(("done", {"text": "", "references": []})))

    ask(bearer, QUESTION)

    assert fake_agent.body() == {"prompt": QUESTION["prompt"], "context": {}}


def test_the_answer_is_relayed_event_by_event(bearer, fake_agent):
    reference = {"kind": "passage", "asset_id": ASSET, "chunk_id": "c-12", "page": 3}
    fake_agent.answer = stream(
        sse(("step", {"tool": "doc_passages", "status": "started", "note": "Reading"})),
        sse(("text", {"delta": "It describes"}), ("text", {"delta": " security"})),
        sse(("reference", reference)),
        sse(("done", {"text": "It describes security", "references": [reference]})),
    )

    response, events = ask(bearer, QUESTION)

    assert response["Content-Type"] == "text/event-stream"
    assert response["X-Accel-Buffering"] == "no"
    assert events == [
        {"event": "step", "tool": "doc_passages", "status": "started", "note": "Reading"},
        {"event": "text", "delta": "It describes"},
        # The leading space survives: DRF would trim it by default.
        {"event": "text", "delta": " security"},
        {"event": "reference", "reference": reference},
        {"event": "done", "text": "It describes security", "references": [reference]},
    ]


def test_the_agents_error_event_ends_the_answer(bearer, fake_agent):
    fake_agent.answer = stream(
        sse(("text", {"delta": "It describes"})),
        sse(("error", {"message": "The model stopped.", "incomplete": True})),
        sse(("text", {"delta": " never sent"})),
    )

    _, events = ask(bearer, QUESTION)

    assert events[-1] == {"event": "error", "message": "The model stopped.", "incomplete": True}
    assert len(events) == 2


def test_a_stream_that_ends_without_done_is_marked_incomplete(bearer, fake_agent):
    fake_agent.answer = stream(sse(("text", {"delta": "It describes"})))

    _, events = ask(bearer, QUESTION)

    assert events == [
        {"event": "text", "delta": "It describes"},
        CUT_OFF,
    ]


def test_a_stream_that_breaks_is_marked_incomplete(bearer, fake_agent):
    fake_agent.answer = stream(
        sse(("text", {"delta": "It describes"})), then=httpx.ReadTimeout("silent")
    )

    _, events = ask(bearer, QUESTION)

    assert events[-1] == CUT_OFF


def test_an_event_outside_the_contract_ends_the_answer_and_is_not_relayed(bearer, fake_agent):
    fake_agent.answer = stream(
        sse(("text", {"delta": "See"})),
        sse(("reference", {"kind": "layer"})),  # no asset_id
        sse(("done", {"text": "See", "references": []})),
    )

    _, events = ask(bearer, QUESTION)

    assert events == [
        {"event": "text", "delta": "See"},
        CUT_OFF,
    ]


def test_an_event_kind_the_contract_lacks_is_skipped(bearer, fake_agent):
    fake_agent.answer = stream(
        sse(("thinking", {"delta": "hmm"})),
        sse(("done", {"text": "", "references": []})),
    )

    _, events = ask(bearer, QUESTION)

    assert [event["event"] for event in events] == ["done"]


def test_fields_the_contract_does_not_name_are_dropped(bearer, fake_agent):
    fake_agent.answer = stream(sse(("text", {"delta": "Hi", "tokens": 3})))

    _, events = ask(bearer, QUESTION)

    assert events[0] == {"event": "text", "delta": "Hi"}


def test_an_unreachable_agent_is_503_and_nothing_streams(bearer, fake_agent):
    fake_agent.answer = httpx.ConnectError("refused")

    response, events = ask(bearer, QUESTION)

    assert response.status_code == 503
    assert events is None


def test_an_agent_that_refuses_is_502(bearer, fake_agent):
    fake_agent.answer = httpx.Response(500, text="Traceback ...")

    response, _ = ask(bearer, QUESTION)

    assert response.status_code == 502
    assert response.json() == {"detail": "The Ask service returned an error"}


def test_an_agent_that_is_not_ready_is_503(bearer, fake_agent):
    fake_agent.answer = httpx.Response(503)

    response, _ = ask(bearer, QUESTION)

    assert response.status_code == 503
