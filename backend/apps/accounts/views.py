from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .cookies import clear_refresh_cookie, read_refresh_cookie, set_refresh_cookie
from .roles import resolve_role
from .serializers import (
    AccessTokenSerializer,
    ChangePasswordSerializer,
    LoginSerializer,
    MeSerializer,
)


class LoginView(APIView):
    """Exchange credentials for a session (HLR-002)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: AccessTokenSerializer,
            400: OpenApiResponse(description="Incorrect username or password."),
        },
        summary="Sign in",
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        refresh = RefreshToken.for_user(serializer.validated_data["user"])
        response = Response({"access": str(refresh.access_token)})
        return set_refresh_cookie(response, str(refresh))


class RefreshView(APIView):
    """
    Renew the session from the refresh cookie (HLR-003).

    The token comes from the cookie, never the request body — the SPA has no
    way to read it, which is the point.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        responses={
            200: AccessTokenSerializer,
            401: OpenApiResponse(description="Missing, expired, or revoked refresh credential."),
        },
        summary="Renew the session",
    )
    def post(self, request):
        raw = read_refresh_cookie(request)
        if not raw:
            return Response(
                {"detail": "No refresh credential."}, status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            refresh = RefreshToken(raw)
            access = str(refresh.access_token)
            # ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION: retire the old
            # token and issue a fresh one, so a stolen cookie has a short life.
            refresh.blacklist()
            new_refresh = RefreshToken.for_user(_user_from(refresh))
        except TokenError:
            # HLR-004: unrenewable session ends and the cookie goes with it.
            response = Response({"detail": "Session expired."}, status=status.HTTP_401_UNAUTHORIZED)
            return clear_refresh_cookie(response)

        response = Response({"access": access})
        return set_refresh_cookie(response, str(new_refresh))


def _user_from(refresh: RefreshToken):
    from django.contrib.auth import get_user_model

    user_id = refresh.payload.get("user_id")
    return get_user_model().objects.get(pk=user_id)


class LogoutView(APIView):
    """End the session: blacklist the refresh token and drop the cookie."""

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Signed out.")},
        summary="Sign out",
    )
    def post(self, request):
        raw = read_refresh_cookie(request)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                # Already expired or revoked — the session is over either way.
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        return clear_refresh_cookie(response)


class MeView(APIView):
    """Identity and role for the signed-in user (HLR-005, HLR-008)."""

    @extend_schema(responses={200: MeSerializer}, summary="Current user")
    def get(self, request):
        return Response(
            MeSerializer(
                {"username": request.user.username, "role": resolve_role(request.user)}
            ).data
        )


class ChangePasswordView(APIView):
    """Change the signed-in user's password (HLR-007)."""

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={
            204: OpenApiResponse(description="Password changed."),
            400: OpenApiResponse(
                description="Current password incorrect, or new password rejected."
            ),
        },
        summary="Change password",
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
