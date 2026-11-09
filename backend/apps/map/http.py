"""What every endpoint that reads the lake shares.

Two views read it — the map's features page and the catalog's document PDF —
and a dead lake or a bad object must answer the same way from both: the same
two status codes, and the same cache headers on what they serve.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class LakeUnreachable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The data lake is unreachable"


class LakeFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The data lake returned an error"


def cacheable(response, etag: str):
    """Mark a lake-backed response as one the browser may keep and must revalidate.

    `no-cache` is not "do not cache": the browser stores the body and asks
    before each reuse, sending the ETag back, and a still-matching one costs a
    catalog lookup and an empty 304 rather than a lake read. Not a long
    max-age: that would keep serving a stale shape after a deploy changes
    one, because the URL would not change. And `private`, because the request
    carries a token and no shared cache should hold the answer.
    """
    response["ETag"] = etag
    response["Cache-Control"] = "private, no-cache"
    return response
