"""The client that speaks GraphQL: what it sends, and how it fails."""

from unittest.mock import patch

import httpx
import pytest

from apps.runs import dagster

from .conftest import run_node


def _answer(data, status_code=200):
    """A fake httpx response carrying a GraphQL body."""
    return httpx.Response(
        status_code, json=data, request=httpx.Request("POST", "http://dagster/graphql")
    )


def test_a_run_is_returned_in_portal_terms_not_dagster_ones():
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {"data": {"runsOrError": {"__typename": "Runs", "results": [run_node()]}}}
        )
        (run,) = dagster.list_runs()

    assert run["id"] == "11111111-1111-1111-1111-111111111111"
    assert run["short_id"] == "11111111"
    # Dagster's float seconds become ISO 8601 UTC before anything above sees them.
    assert run["created_at"] == "2025-09-04T15:33:20+00:00"
    assert run["duration_seconds"] == 60.0
    assert run["trigger"] == {"kind": "schedule", "name": "weekly_schedule"}
    assert run["assets"] == ["bronze/sync"]
    assert run["steps_succeeded"] == 5


def test_a_run_with_no_schedule_or_sensor_tag_reads_as_manual():
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {
                "data": {
                    "runsOrError": {
                        "__typename": "Runs",
                        "results": [run_node(tags=[{"key": "user", "value": "admin-user"}])],
                    }
                }
            }
        )
        (run,) = dagster.list_runs()

    assert run["trigger"] == {"kind": "manual", "name": "admin-user"}


def test_the_job_filter_is_sent_as_pipelineName():
    """RunsFilter has no jobName key, only pipelineName."""
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {"data": {"runsOrError": {"__typename": "Runs", "results": []}}}
        )
        dagster.list_runs(job_name="weekly_pipeline", statuses=["SUCCESS"])

    sent = post.call_args.kwargs["json"]["variables"]["filter"]
    assert sent == {"statuses": ["SUCCESS"], "pipelineName": "weekly_pipeline"}


def test_an_unknown_run_is_none_rather_than_an_error():
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {"data": {"runOrError": {"__typename": "RunNotFoundError", "message": "nope"}}}
        )
        assert dagster.get_run("11111111-1111-1111-1111-111111111111") is None


def test_an_error_branch_becomes_a_dagster_error():
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {"data": {"runsOrError": {"__typename": "PythonError", "message": "boom"}}}
        )
        with pytest.raises(dagster.DagsterError, match="boom"):
            dagster.list_runs()


def test_a_rejected_query_is_an_error_even_though_dagster_answers_500():
    """Dagster returns HTTP 500 with a real GraphQL body when it rejects a
    query. That is Dagster answering, not Dagster being down."""
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {"data": None, "errors": [{"message": "does not exist in 'RunStatus' enum"}]}, 500
        )
        with pytest.raises(dagster.DagsterError, match="RunStatus"):
            dagster.list_runs()


def test_a_timeout_is_unavailable_not_an_error():
    with patch("apps.runs.dagster.httpx.post", side_effect=httpx.ReadTimeout("too slow")):
        with pytest.raises(dagster.DagsterUnavailable):
            dagster.list_runs()


def test_a_refused_connection_is_unavailable():
    with patch("apps.runs.dagster.httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(dagster.DagsterUnavailable):
            dagster.list_runs()


def test_steps_come_from_stepStats_and_are_not_derived_from_the_log():
    node = run_node()
    node["stepStats"] = [
        {
            "stepKey": "silver_vector",
            "status": "SUCCESS",
            "startTime": 1757000010.0,
            "endTime": 1757000040.0,
        }
    ]
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer({"data": {"runOrError": {"__typename": "Run", **node}}})
        detail = dagster.get_run("11111111-1111-1111-1111-111111111111")

    assert detail["steps"] == [
        {
            "step_key": "silver_vector",
            "status": "SUCCESS",
            "started_at": "2025-09-04T15:33:30+00:00",
            "ended_at": "2025-09-04T15:34:00+00:00",
            "duration_seconds": 30.0,
        }
    ]
    # The run succeeded, so no log was read looking for a failure.
    assert detail["failure_summary"] is None
    assert post.call_count == 1


def test_a_failed_run_reports_the_first_error_from_its_log():
    node = run_node(status="FAILURE")
    node["stepStats"] = []
    logs = {
        "__typename": "EventConnection",
        "cursor": "c1",
        "hasMore": False,
        "events": [
            {
                "__typename": "LogMessageEvent",
                "message": "starting",
                "timestamp": "1757000010000",
                "level": "INFO",
                "stepKey": None,
            },
            {
                "__typename": "ExecutionStepFailureEvent",
                "message": "step failed",
                "timestamp": "1757000020000",
                "level": "ERROR",
                "stepKey": "bronze_sync",
                "error": {"message": "rclone exited 1", "stack": ["line one"]},
            },
        ],
    }
    with patch("apps.runs.dagster.httpx.post") as post:
        post.side_effect = [
            _answer({"data": {"runOrError": {"__typename": "Run", **node}}}),
            _answer({"data": {"logsForRun": logs}}),
        ]
        detail = dagster.get_run("11111111-1111-1111-1111-111111111111")

    assert detail["failure_summary"] == "rclone exited 1"


def test_an_events_timestamp_is_milliseconds_unlike_every_other_time():
    logs = {
        "__typename": "EventConnection",
        "cursor": "c1",
        "hasMore": True,
        "events": [
            {
                "__typename": "LogMessageEvent",
                "message": "hello",
                "timestamp": "1757000010000",
                "level": "INFO",
                "stepKey": "bronze_sync",
            }
        ],
    }
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer({"data": {"logsForRun": logs}})
        page = dagster.get_run_logs("11111111-1111-1111-1111-111111111111")

    assert page["events"][0]["timestamp"] == "2025-09-04T15:33:30+00:00"
    assert page["events"][0]["error"] is None
    assert page == {**page, "next_cursor": "c1", "has_more": True}
    # The log cursor argument is afterCursor, not cursor.
    assert "afterCursor" in post.call_args.kwargs["json"]["variables"]


def test_launch_sends_the_selector_dagster_requires():
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {
                "data": {
                    "launchRun": {
                        "__typename": "LaunchRunSuccess",
                        "run": {"runId": "abc", "status": "QUEUED"},
                    }
                }
            }
        )
        launched = dagster.launch_run("weekly_pipeline")

    selector = post.call_args.kwargs["json"]["variables"]["executionParams"]["selector"]
    assert selector == {
        "jobName": "weekly_pipeline",
        "repositoryName": "__repository__",
        "repositoryLocationName": "gobase_orchestration.definitions",
    }
    assert launched == {"id": "abc", "status": "QUEUED"}


def test_a_conflicting_launch_is_an_error_branch():
    with patch("apps.runs.dagster.httpx.post") as post:
        post.return_value = _answer(
            {"data": {"launchRun": {"__typename": "RunConflict", "message": "already running"}}}
        )
        with pytest.raises(dagster.DagsterError, match="already running"):
            dagster.launch_run("weekly_pipeline")
