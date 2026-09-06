"""Refresh-cookie helpers — the single place the cookie contract is expressed."""

from django.conf import settings
from rest_framework.response import Response


def set_refresh_cookie(response: Response, token: str) -> Response:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )
    return response


def clear_refresh_cookie(response: Response) -> Response:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )
    return response


def read_refresh_cookie(request) -> str | None:
    return request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
