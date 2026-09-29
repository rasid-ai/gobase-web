"""The Places API: turning typed text into somewhere on the map.

Its own app because neither page that uses it owns the question. `apps/map`
already means "assets at this point" and the Assets page has no map on it;
`apps/catalog` is the knowledge base reader and geocoding touches no table
(docs/adr/010, docs/adr/011).

Nothing is stored, so there is no model and no migration — and nothing is
cached either, which is a licensing decision as much as an infrastructure one
(docs/adr/011).
"""

import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from . import esri
from .serializers import PlaceSearchQuerySerializer, PlaceSearchSerializer

logger = logging.getLogger(__name__)


class GeocoderUnreachable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Address search is unavailable"


class GeocoderFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Address search returned an error"


class PlaceSearchView(APIView):
    """Find places by name or address."""

    @extend_schema(
        parameters=[PlaceSearchQuerySerializer],
        responses={
            200: PlaceSearchSerializer,
            400: OpenApiResponse(description="Missing or empty search text."),
            502: OpenApiResponse(description="The geocoder returned an error."),
            503: OpenApiResponse(description="The geocoder is unreachable, or no API key is set."),
        },
        operation_id="places_search",
        summary="Search for a place by name or address",
        tags=["places"],
    )
    def get(self, request):
        query = PlaceSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        # Checked before the call, not after it: with no key every request
        # would spend a round trip to be told the same thing. The detail
        # differs from the unreachable one so an operator can tell which of the
        # two happened from the log, while the caller sees one message.
        if not settings.ESRI_API_KEY:
            logger.warning("Address search asked for, but no API key is configured")
            raise GeocoderUnreachable("Address search is not configured")

        return Response(PlaceSearchSerializer({"results": _find(query.validated_data["q"])}).data)


def _find(text: str) -> list[dict]:
    """Ask the geocoder, turning its two failure modes into HTTP ones.

    Unreachable is 503 (try again later); an error object is 502 (it is up and
    refusing). Neither is a 500: the portal itself is fine.

    Unlike apps/runs/views.py, the 502 does not pass the upstream message on.
    Dagster's error branches describe the caller's own request, so a caller can
    act on them; the geocoder's describe our credentials — "Invalid token",
    "Token required" — which is configuration, aimed at someone who cannot fix
    it. It goes to the log instead.
    """
    try:
        return esri.find_places(text)
    except esri.EsriUnavailable as exc:
        logger.warning("Geocoder unreachable: %s", exc)
        raise GeocoderUnreachable() from exc
    except esri.EsriError as exc:
        logger.warning("Geocoder error: %s", exc)
        raise GeocoderFailed() from exc
