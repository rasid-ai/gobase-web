"""
Self-service API keys: a desktop client trades a username and password for a key
(docs/adr/021). Its own module, so the session views in views.py stay as they are.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ApiKey
from .serializers import ApiKeyIssuedSerializer, ApiKeyIssueSerializer


class ApiKeyIssueView(APIView):
    """
    Exchange credentials for an API key.

    Checked exactly as login checks them, with the same single error message.
    No session is started: the client keeps the key, never the password.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=ApiKeyIssueSerializer,
        responses={
            201: ApiKeyIssuedSerializer,
            400: OpenApiResponse(description="Incorrect username or password, or no name."),
        },
        summary="Get an API key",
    )
    def post(self, request):
        serializer = ApiKeyIssueSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        key, raw = ApiKey.issue_replacing(
            serializer.validated_data["user"], serializer.validated_data["name"]
        )
        response = Response(
            ApiKeyIssuedSerializer(
                {"key": raw, "prefix": key.prefix, "name": key.name, "created_at": key.created_at}
            ).data,
            status=status.HTTP_201_CREATED,
        )
        # The body holds a secret: no proxy or client cache may keep it.
        response["Cache-Control"] = "no-store"
        return response
