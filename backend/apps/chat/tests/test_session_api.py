"""GET /api/chat/sessions, GET and DELETE /api/chat/sessions/{id} (docs/adr/025).

The portal stores nothing about chat: each call goes to the agent as the
signed-in user, and what comes back is cut to the contract.
"""

import httpx

from .conftest import AGENT_URL, ASSET, SESSION, TOKEN, session_row

LIST = "/api/chat/sessions"
ONE = f"/api/chat/sessions/{SESSION}"


def test_signing_in_is_required(api, fake_agent):
    assert api.get(LIST).status_code == 401
    assert fake_agent.requests == []


def test_the_list_asks_the_agent_for_this_user_with_the_service_token(as_viewer, user, fake_agent):
    fake_agent.answer = httpx.Response(200, json={"results": [session_row()]})

    response = as_viewer.get(LIST)

    assert response.status_code == 200
    assert response.json() == {"results": [session_row()]}
    assert str(fake_agent.last.url) == f"{AGENT_URL}/v1/users/{user.pk}/sessions"
    assert fake_agent.last.headers["Authorization"] == f"Bearer {TOKEN}"


def test_fields_the_contract_does_not_name_are_dropped(as_viewer, fake_agent):
    fake_agent.answer = httpx.Response(
        200, json={"results": [session_row(bucket_key="users/1/session_x")], "next": "y"}
    )

    assert as_viewer.get(LIST).json() == {"results": [session_row()]}


def test_no_agent_url_is_503_before_any_call(as_viewer, fake_agent, settings):
    settings.AGENT_URL = ""

    response = as_viewer.get(LIST)

    assert response.status_code == 503
    assert fake_agent.requests == []


def test_an_unreachable_agent_is_503(as_viewer, fake_agent):
    fake_agent.answer = httpx.ConnectError("refused")

    assert as_viewer.get(LIST).status_code == 503


def test_an_agent_that_is_not_ready_is_503(as_viewer, fake_agent):
    fake_agent.answer = httpx.Response(503)

    assert as_viewer.get(LIST).status_code == 503


def test_an_agent_that_refuses_is_502(as_viewer, fake_agent):
    # 401 is the agent rejecting our token: configuration, not the caller's fault.
    fake_agent.answer = httpx.Response(401, json={"detail": "bad token"})

    response = as_viewer.get(LIST)

    assert response.status_code == 502
    assert "token" not in response.content.decode()


def test_an_answer_outside_the_contract_is_502(as_viewer, fake_agent):
    fake_agent.answer = httpx.Response(200, json={"results": [{"session_id": "not-a-uuid"}]})

    assert as_viewer.get(LIST).status_code == 502


def test_an_answer_that_is_not_json_is_502(as_viewer, fake_agent):
    fake_agent.answer = httpx.Response(200, text="<html>")

    assert as_viewer.get(LIST).status_code == 502


def test_a_session_comes_back_with_its_turns_in_order(as_viewer, user, fake_agent):
    turns = [
        {
            "prompt": "What data is there here?",
            "text": "Two datasets cover this point.",
            "references": [
                {
                    "kind": "asset",
                    "handle": "A1",
                    "asset_id": ASSET,
                    "name": "education_facilities",
                    "data_type": "vector",
                    "cited": True,
                },
                {"kind": "asset", "handle": "A2", "asset_id": ASSET, "cited": False},
            ],
            "incomplete": False,
        },
        {
            "prompt": "And the airport report?",
            "text": "It describes security as",
            "references": [],
            "incomplete": True,
        },
    ]
    fake_agent.answer = httpx.Response(200, json={**session_row(), "turns": turns})

    response = as_viewer.get(ONE)

    assert response.status_code == 200
    assert response.json()["turns"] == turns
    assert str(fake_agent.last.url) == f"{AGENT_URL}/v1/users/{user.pk}/sessions/{SESSION}"


def test_a_turn_with_no_incomplete_flag_is_whole(as_viewer, fake_agent):
    turn = {"prompt": "Hi", "text": "Hello.", "references": []}
    fake_agent.answer = httpx.Response(200, json={**session_row(), "turns": [turn]})

    assert as_viewer.get(ONE).json()["turns"][0]["incomplete"] is False


def test_a_session_the_agent_does_not_have_for_this_user_is_404(as_viewer, fake_agent):
    fake_agent.answer = httpx.Response(404)

    assert as_viewer.get(ONE).status_code == 404


def test_a_session_id_that_is_not_a_uuid_never_reaches_the_agent(as_viewer, fake_agent):
    assert as_viewer.get("/api/chat/sessions/..%2Fother").status_code == 404
    assert fake_agent.requests == []


def test_deleting_asks_the_agent_to_delete(as_viewer, user, fake_agent):
    fake_agent.answer = httpx.Response(204)

    response = as_viewer.delete(ONE)

    assert response.status_code == 204
    assert fake_agent.last.method == "DELETE"
    assert str(fake_agent.last.url) == f"{AGENT_URL}/v1/users/{user.pk}/sessions/{SESSION}"


def test_deleting_what_is_not_there_is_404(as_viewer, fake_agent):
    fake_agent.answer = httpx.Response(404)

    assert as_viewer.delete(ONE).status_code == 404
