"""What the portal sends the geocoder, and what it makes of the answer."""

from unittest.mock import patch

import httpx
import pytest

from apps.places import esri

from .conftest import candidate


def answer(body, status_code=200):
    return httpx.Response(
        status_code, json=body, request=httpx.Request("POST", "https://geocoder/x")
    )


def call(body, status_code=200, text="Beirut"):
    with patch("apps.places.esri.httpx.post") as post:
        post.return_value = answer(body, status_code)
        return esri.find_places(text), post


def test_a_candidate_comes_back_in_portal_terms():
    places, _ = call({"candidates": [candidate()]})

    assert places == [
        {
            "name": "Beirut, Lebanon",
            "lat": 33.8938,
            "lon": 35.5018,
            "bbox": [35.4, 33.8, 35.6, 34.0],
        }
    ]


def test_the_api_key_is_in_the_body_and_never_in_the_url(settings):
    # The whole reason this is a POST. A key in a query string reaches proxy
    # logs and can surface inside an httpx exception's text.
    settings.ESRI_API_KEY = "sekrit"
    _, post = call({"candidates": []})

    url = post.call_args.args[0]
    assert "params" not in post.call_args.kwargs
    assert "sekrit" not in url
    assert post.call_args.kwargs["data"]["token"] == "sekrit"


def test_the_request_asks_for_five_candidates_in_4326_and_does_not_store_them(settings):
    settings.ESRI_MAX_CANDIDATES = 5
    _, post = call({"candidates": []}, text="Beirut")

    sent = post.call_args.kwargs["data"]
    assert sent["singleLine"] == "Beirut"
    assert sent["maxLocations"] == 5
    assert sent["outSR"] == 4326
    # Stored geocoding has no free tier at all (docs/adr/011).
    assert sent["forStorage"] == "false"


def test_an_error_body_on_http_200_is_an_error_not_an_outage():
    # The reason the body is read before the status code: the geocoder reports
    # a bad token as HTTP 200 with an `error` object.
    with patch("apps.places.esri.httpx.post") as post:
        post.return_value = answer({"error": {"code": 498, "message": "Invalid token"}})
        with pytest.raises(esri.EsriError, match="Invalid token"):
            esri.find_places("Beirut")


@pytest.mark.parametrize(
    "exc",
    [httpx.TimeoutException("too slow"), httpx.ConnectError("refused")],
)
def test_a_network_failure_is_unavailable(exc):
    with patch("apps.places.esri.httpx.post", side_effect=exc):
        with pytest.raises(esri.EsriUnavailable):
            esri.find_places("Beirut")


def test_the_upstream_url_never_reaches_the_exception_message(settings):
    # EsriUnavailable carries the exception type, not its text, because httpx
    # messages carry the URL and the URL is one refactor from carrying the key.
    settings.ESRI_API_KEY = "sekrit"
    with patch(
        "apps.places.esri.httpx.post", side_effect=httpx.ConnectError("https://x?token=sekrit")
    ):
        with pytest.raises(esri.EsriUnavailable) as raised:
            esri.find_places("Beirut")

    assert "sekrit" not in str(raised.value)


def test_a_non_json_failure_is_unavailable():
    with patch("apps.places.esri.httpx.post") as post:
        post.return_value = httpx.Response(
            502, text="<html>bad gateway", request=httpx.Request("POST", "https://geocoder/x")
        )
        with pytest.raises(esri.EsriUnavailable):
            esri.find_places("Beirut")


def test_no_candidates_key_is_an_empty_list_not_an_error():
    places, _ = call({})
    assert places == []


def test_a_candidate_with_no_point_is_dropped():
    # A row that would do nothing when picked is worse than no row.
    places, _ = call({"candidates": [candidate(location=None), candidate()]})
    assert [place["name"] for place in places] == ["Beirut, Lebanon"]


def test_a_candidate_with_no_extent_has_no_bbox():
    places, _ = call({"candidates": [candidate(extent=None)]})
    assert places[0]["bbox"] is None


def test_an_inside_out_extent_has_no_bbox():
    # A place spanning the antimeridian comes back with xmin > xmax. Neither
    # half is the place, so the portal reports no area and keeps the point.
    inside_out = {"xmin": 179.5, "ymin": 33.8, "xmax": -179.5, "ymax": 34.0}
    places, _ = call({"candidates": [candidate(extent=inside_out)]})

    assert places[0]["bbox"] is None
    assert places[0]["lon"] == 35.5018
