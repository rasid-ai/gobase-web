"""The Map API for desktop clients: where a raster is, and credentials to read it.

Its own module so it stays apart from views.py, which the features endpoint
keeps busy (docs/adr/015).
"""

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import kb

from . import sts
from .serializers import RasterAccessSerializer
from .views import LakeFailed, LakeUnreachable

logger = logging.getLogger(__name__)


class RasterAccessNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "This portal does not serve rasters to desktop clients"


class RasterAccessView(APIView):
    """Short-lived, read-only lake credentials for one raster, and its address.

    ArcGIS Pro cannot open a COG from a URL. It reads one through a cloud
    storage connection, which signs its own range requests to the bucket, so
    the portal hands out what that connection needs and never the pixels
    (docs/adr/022). Raster only: any other asset is a 404, as `/data` is for
    anything but a vector.

    A GET although each call issues new credentials: an API key may only
    read (docs/adr/021), and nothing in the portal or the lake changes.
    """

    @extend_schema(
        responses={
            200: RasterAccessSerializer,
            404: OpenApiResponse(description="No active raster asset with that id."),
            502: OpenApiResponse(
                description="The lake answered with an error, or the raster is not in the lake."
            ),
            503: OpenApiResponse(
                description=(
                    "Raster access is not set up on this portal, or the lake could not be reached."
                )
            ),
        },
        operation_id="map_asset_raster_access",
        summary="Credentials to read a raster from the lake",
        tags=["map"],
    )
    def get(self, request, asset_id):
        if not sts.configured():
            raise RasterAccessNotConfigured()

        uri = kb.raster_source_uri(asset_id)
        if uri is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            bucket, key = sts.split_s3_uri(uri)
        except ValueError as exc:
            # The catalog's fault, not the caller's: every raster should be in the lake.
            logger.error("Raster %s is not an s3:// object, so it cannot be shared", asset_id)
            raise LakeFailed() from exc

        try:
            credentials = sts.issue(bucket, key, session_name=f"portal-user-{request.user.pk}")
        except sts.IssuerUnavailable as exc:
            raise LakeUnreachable() from exc
        except sts.IssueFailed as exc:
            raise LakeFailed() from exc

        logger.info("Raster credentials for %s issued to user %s", asset_id, request.user.pk)
        body = RasterAccessSerializer(
            {
                "asset_id": asset_id,
                "url": sts.object_url(bucket, key),
                "endpoint": sts.public_endpoint(),
                "region": sts.region(),
                "bucket": bucket,
                "key": key,
                "credentials": credentials,
            }
        ).data
        response = Response(body)
        # The body is a secret. No cache, private or shared, may keep it.
        response["Cache-Control"] = "no-store"
        return response
