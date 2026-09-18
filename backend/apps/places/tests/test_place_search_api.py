"""What GET /api/places/search answers."""

from unittest.mock import patch

import pytest

from apps.places import esri

URL = "/api/places/search"

BEIRUT = {
    "name": "Beirut, Lebanon",
    "lat": 33.8938,
    "lon": 35.5018,
    "bbox": [35.4, 33.8, 35.6, 34.0],
}


def test_a_search_needs_a_session(api):
    assert api.get(URL, {"q": "Beirut"}).status_code == 401


def test_a_match_comes_back_as_results(as_viewer):
    with patch("apps.places.views.esri.find_places", return_value=[BEIRUT]) as found:
        response = as_viewer.get(URL, {"q": "Beirut"})

    assert response.status_code == 200
    assert response.data == {"results": [BEIRUT]}
    assert found.call_args.args[0] == "Beirut"


def test_nothing_found_is_an_empty_list_not_an_error(as_viewer):
    # "Nowhere is called that" is an answer, like a point nothing covers.
    with patch("apps.places.views.esri.find_places", return_value=[]):
        response = as_viewer.get(URL, {"q": "zzzzzzzz"})

    assert response.status_code == 200
    assert response.data == {"results": []}


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "   "}])
def test_empty_search_text_is_rejected_without_asking_the_geocoder(as_viewer, params):
    with patch("apps.places.views.esri.find_places") as found:
        response = as_viewer.get(URL, params)

    assert response.status_code == 400
    assert found.call_count == 0


def test_an_unreachable_geocoder_is_503(as_viewer):
    with patch(
        "apps.places.views.esri.find_places", side_effect=esri.EsriUnavailable("ConnectError")
    ):
        response = as_viewer.get(URL, {"q": "Beirut"})

    assert response.status_code == 503


def test_a_refusing_geocoder_is_502_and_says_nothing_about_why(as_viewer):
    # The geocoder's error branches describe our credentials, not the caller's
    # request. A viewer cannot act on "Invalid token" and should not read it.
    with patch("apps.places.views.esri.find_places", side_effect=esri.EsriError("Invalid token")):
        response = as_viewer.get(URL, {"q": "Beirut"})

    assert response.status_code == 502
    assert "Invalid token" not in str(response.data)


def test_no_api_key_is_503_and_never_reaches_the_geocoder(as_viewer, settings):
    # The portal runs without an ArcGIS account. It just cannot do this.
    settings.ESRI_API_KEY = ""
    with patch("apps.places.views.esri.find_places") as found:
        response = as_viewer.get(URL, {"q": "Beirut"})

    assert response.status_code == 503
    assert found.call_count == 0
