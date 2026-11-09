"""What the portal sends GoDoc's RAG server, and what it makes of the answer."""

from unittest.mock import patch

import httpx
import pytest

from apps.catalog import godoc

MODEL = "BAAI/bge-small-en-v1.5"
VECTOR = [0.1, -0.2, 0.3]


def answer(body, status_code=200):
    return httpx.Response(
        status_code, json=body, request=httpx.Request("POST", "http://godoc/rag/embed")
    )


def call(body, status_code=200, text="airport security"):
    with patch("apps.catalog.godoc.httpx.post") as post:
        post.return_value = answer(body, status_code)
        return godoc.embed(text), post


@pytest.fixture(autouse=True)
def configured(settings):
    settings.GODOC_URL = "http://godoc:8003"
    settings.GODOC_TIMEOUT_SECONDS = 1.5


def test_the_model_and_the_first_vector_come_back():
    (model, vector), _ = call({"model": MODEL, "dim": 3, "normalized": True, "vectors": [VECTOR]})

    assert model == MODEL
    assert vector == VECTOR


def test_the_text_is_sent_bare_as_the_one_item_of_texts():
    """No instruction prefix: the cards were embedded without one too."""
    _, post = call({"model": MODEL, "vectors": [VECTOR]}, text="reopening an airport")

    assert post.call_args.args[0] == "http://godoc:8003/rag/embed"
    assert post.call_args.kwargs["json"] == {"texts": ["reopening an airport"]}
    assert post.call_args.kwargs["timeout"] == 1.5


@pytest.mark.parametrize(
    "exc",
    [httpx.TimeoutException("too slow"), httpx.ConnectError("refused")],
)
def test_a_network_failure_is_unavailable(exc):
    with patch("apps.catalog.godoc.httpx.post", side_effect=exc):
        with pytest.raises(godoc.GoDocUnavailable):
            godoc.embed("airport security")


def test_the_question_never_reaches_the_exception_message():
    # The question is chat content (CLAUDE.md). httpx's own message can quote
    # the request, so only the exception's type is carried.
    quoted = httpx.ConnectError('POST /rag/embed {"texts": ["secret plans"]}')
    with patch("apps.catalog.godoc.httpx.post", side_effect=quoted):
        with pytest.raises(godoc.GoDocUnavailable) as raised:
            godoc.embed("secret plans")

    assert "secret plans" not in str(raised.value)


def test_a_server_failure_is_unavailable():
    with patch("apps.catalog.godoc.httpx.post") as post:
        post.return_value = answer({"detail": "model not loaded"}, 500)
        with pytest.raises(godoc.GoDocUnavailable):
            godoc.embed("airport security")


@pytest.mark.parametrize("status_code", [400, 413])
def test_a_refused_request_is_an_error_not_an_outage(status_code):
    # 400 is a body it will not take, 413 more texts than it allows: the
    # server is up, and the portal's request is what is wrong.
    with patch("apps.catalog.godoc.httpx.post") as post:
        post.return_value = answer({"detail": "no"}, status_code)
        with pytest.raises(godoc.GoDocError):
            godoc.embed("airport security")


def test_a_non_json_answer_is_unavailable():
    with patch("apps.catalog.godoc.httpx.post") as post:
        post.return_value = httpx.Response(
            200, text="<html>", request=httpx.Request("POST", "http://godoc/rag/embed")
        )
        with pytest.raises(godoc.GoDocUnavailable):
            godoc.embed("airport security")


@pytest.mark.parametrize(
    "body",
    [{"model": MODEL, "vectors": []}, {"model": MODEL}, {"vectors": [VECTOR]}, []],
    ids=["no vectors", "no vectors key", "no model", "not an object"],
)
def test_an_answer_without_a_model_and_a_vector_is_an_error(body):
    with patch("apps.catalog.godoc.httpx.post") as post:
        post.return_value = answer(body)
        with pytest.raises(godoc.GoDocError):
            godoc.embed("airport security")
