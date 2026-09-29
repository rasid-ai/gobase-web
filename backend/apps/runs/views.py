"""The Runs API: a live proxy in front of Dagster.

Nothing here is stored. Every request asks Dagster and shapes the answer, which
is why there is no model and no migration (docs/adr/004). The pipeline runs
once a week, so the volume never justifies mirroring it.
"""

import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import IsAdmin

from . import dagster
from .serializers import (
    LaunchedRunSerializer,
    RunDetailSerializer,
    RunListSerializer,
    RunLogsSerializer,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class DagsterUnreachable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Dagster is unreachable"


class DagsterFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Dagster returned an error"


def _ask(call, *args, **kwargs):
    """Call Dagster, turning its two failure modes into HTTP ones.

    Unreachable is 503 (try again later); an error branch is 502 (Dagster is up
    and refusing). Neither is a 500: the portal itself is fine.
    """
    try:
        return call(*args, **kwargs)
    except dagster.DagsterUnavailable as exc:
        logger.warning("Dagster unreachable: %s", exc)
        raise DagsterUnreachable() from exc
    except dagster.DagsterError as exc:
        logger.warning("Dagster error: %s", exc)
        raise DagsterFailed(f"Dagster returned an error: {exc}") from exc


class _RunQuerySerializer(serializers.Serializer):
    """The list filters, validated before anything reaches Dagster."""

    status = serializers.CharField(required=False)
    job = serializers.CharField(required=False)
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=MAX_PAGE_SIZE, default=DEFAULT_PAGE_SIZE
    )
    cursor = serializers.CharField(required=False)

    def validate_status(self, value):
        """Comma-separated statuses. Checked here so a typo is a 400, not a 502."""
        statuses = [item.strip().upper() for item in value.split(",") if item.strip()]
        unknown = [item for item in statuses if item not in dagster.RUN_STATUSES]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown run status {', '.join(unknown)}. "
                f"Expected one of {', '.join(dagster.RUN_STATUSES)}."
            )
        return statuses


class RunListView(APIView):
    """List pipeline runs, newest first."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                description="Comma-separated run statuses, e.g. SUCCESS,FAILURE.",
            ),
            OpenApiParameter("job", str, description="Filter to one job name."),
            OpenApiParameter("limit", int, description="Page size, 1-100. Defaults to 25."),
            OpenApiParameter("cursor", str, description="The previous page's next_cursor."),
        ],
        responses={
            200: RunListSerializer,
            400: OpenApiResponse(description="Unknown run status, or a bad limit."),
            502: OpenApiResponse(description="Dagster returned an error."),
            503: OpenApiResponse(description="Dagster is unreachable."),
        },
        operation_id="runs_list",
        summary="Pipeline runs",
        tags=["runs"],
    )
    def get(self, request):
        query = _RunQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        limit = query.validated_data["limit"]

        runs = _ask(
            dagster.list_runs,
            statuses=query.validated_data.get("status"),
            job_name=query.validated_data.get("job"),
            limit=limit,
            cursor=query.validated_data.get("cursor"),
        )

        # A short page is the last page. A full one may or may not be, so the
        # cursor is offered and the next request settles it.
        next_cursor = runs[-1]["id"] if len(runs) == limit else None
        return Response(RunListSerializer({"results": runs, "next_cursor": next_cursor}).data)


class RunDetailView(APIView):
    """One run, with its per-step breakdown."""

    @extend_schema(
        responses={
            200: RunDetailSerializer,
            404: OpenApiResponse(description="No run with that id."),
            502: OpenApiResponse(description="Dagster returned an error."),
            503: OpenApiResponse(description="Dagster is unreachable."),
        },
        operation_id="runs_detail",
        summary="Run detail and steps",
        tags=["runs"],
    )
    def get(self, request, run_id):
        detail = _ask(dagster.get_run, str(run_id))
        if detail is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(RunDetailSerializer(detail).data)


class _LogQuerySerializer(serializers.Serializer):
    cursor = serializers.CharField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=1000, default=200)


class RunLogsView(APIView):
    """A page of one run's event log."""

    @extend_schema(
        parameters=[
            OpenApiParameter("cursor", str, description="The previous page's next_cursor."),
            OpenApiParameter("limit", int, description="Page size, 1-1000. Defaults to 200."),
        ],
        responses={
            200: RunLogsSerializer,
            400: OpenApiResponse(description="Bad limit."),
            404: OpenApiResponse(description="No run with that id."),
            502: OpenApiResponse(description="Dagster returned an error."),
            503: OpenApiResponse(description="Dagster is unreachable."),
        },
        operation_id="runs_logs",
        summary="Run event log",
        tags=["runs"],
    )
    def get(self, request, run_id):
        query = _LogQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        page = _ask(
            dagster.get_run_logs,
            str(run_id),
            cursor=query.validated_data.get("cursor"),
            limit=query.validated_data["limit"],
        )
        if page is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(RunLogsSerializer(page).data)


class RunTriggerView(APIView):
    """Start one run of the configured job. Admin only."""

    permission_classes = [IsAdmin]

    @extend_schema(
        request=None,
        responses={
            202: LaunchedRunSerializer,
            403: OpenApiResponse(description="Viewers may not launch runs."),
            409: OpenApiResponse(description="A run is already in progress."),
            502: OpenApiResponse(description="Dagster returned an error."),
            503: OpenApiResponse(description="Dagster is unreachable."),
        },
        operation_id="runs_trigger",
        summary="Launch a pipeline run",
        tags=["runs"],
    )
    def post(self, request):
        job_name = settings.DAGSTER_JOB_NAME

        # Ask before launching. This is a guess about a moving target -- a run
        # can start between the check and the launch -- but it catches the
        # double-click, which is what actually happens (specs/runs.md).
        in_flight = _ask(
            dagster.list_runs,
            statuses=dagster.IN_PROGRESS_STATUSES,
            job_name=job_name,
            limit=1,
        )
        if in_flight:
            return Response(
                {"detail": "A run is already in progress", "run_id": in_flight[0]["id"]},
                status=status.HTTP_409_CONFLICT,
            )

        launched = _ask(dagster.launch_run, job_name)
        # The audit line for a manual launch: who, and what it started.
        logger.info("%s launched job %s as run %s", request.user.username, job_name, launched["id"])
        return Response(LaunchedRunSerializer(launched).data, status=status.HTTP_202_ACCEPTED)
