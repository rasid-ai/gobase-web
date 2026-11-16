"""
Liveness endpoint for the deploy pipeline.

`infra/deploy.sh` blocks on this after `docker compose up -d`, so it has to
answer the question a deploy actually asks: can this container serve a
request that reaches the database it owns? A process that is up but cannot
reach Postgres is a failed deploy, not a healthy one.

`kb` is deliberately not probed. It is read-only, unused before the Map/Ask
slices, and a knowledge base outage must never fail a portal deploy.
"""

from django.db import DatabaseError, connections
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)


class HealthView(APIView):
    """Report whether this container can serve requests against `portal`."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=None,
        responses={
            200: HealthSerializer,
            503: OpenApiResponse(description="The portal database is unreachable."),
        },
        summary="Health check",
        tags=["health"],
    )
    def get(self, request):
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            return Response(
                {"status": "database unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok"})
