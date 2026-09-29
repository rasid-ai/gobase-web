"""The Runs endpoints: who may call them, and what they do when Dagster misbehaves.

The Dagster client is faked at its own boundary — these tests never open a
socket and never need a Dagster.
"""

from unittest.mock import patch

import pytest

from apps.runs import dagster

pytestmark = pytest.mark.django_db

RUN_ID = "11111111-1111-1111-1111-111111111111"


def portal_run(run_id=RUN_ID, **overrides):
    """A run as the client hands it up, already in portal terms."""
    run = {
        "id": run_id,
        "short_id": run_id[:8],
        "job_name": "weekly_pipeline",
        "status": "SUCCESS",
        "created_at": "2025-09-04T15:33:20+00:00",
        "started_at": "2025-09-04T15:33:30+00:00",
        "ended_at": "2025-09-04T15:34:30+00:00",
        "duration_seconds": 60.0,
        "trigger": {"kind": "manual", "name": "admin-user"},
        "partition": None,
        "steps_succeeded": 5,
        "steps_failed": 0,
        "materializations": 5,
        "assets": ["bronze/sync"],
    }
    run.update(overrides)
    return run


# --- reading ---------------------------------------------------------------


def test_anonymous_callers_get_401(api):
    assert api.get("/api/runs/").status_code == 401
    assert api.get(f"/api/runs/{RUN_ID}").status_code == 401
    assert api.post("/api/runs/trigger").status_code == 401


def test_a_viewer_can_list_runs(as_viewer):
    with patch("apps.runs.views.dagster.list_runs", return_value=[portal_run()]) as listed:
        response = as_viewer.get("/api/runs/")

    assert response.status_code == 200
    assert response.data["results"][0]["short_id"] == "11111111"
    assert response.data["results"][0]["trigger"]["kind"] == "manual"
    assert listed.call_args.kwargs["limit"] == 25


def test_a_full_page_offers_a_cursor_and_a_short_page_does_not(as_viewer):
    runs = [portal_run(run_id=f"1111111{n}-1111-1111-1111-111111111111") for n in range(2)]
    with patch("apps.runs.views.dagster.list_runs", return_value=runs):
        full = as_viewer.get("/api/runs/?limit=2")
        short = as_viewer.get("/api/runs/?limit=5")

    assert full.data["next_cursor"] == runs[-1]["id"]
    assert short.data["next_cursor"] is None


def test_the_filters_reach_the_client(as_viewer):
    with patch("apps.runs.views.dagster.list_runs", return_value=[]) as listed:
        response = as_viewer.get("/api/runs/?status=success,FAILURE&job=weekly_pipeline&cursor=abc")

    assert response.status_code == 200
    assert listed.call_args.kwargs["statuses"] == ["SUCCESS", "FAILURE"]
    assert listed.call_args.kwargs["job_name"] == "weekly_pipeline"
    assert listed.call_args.kwargs["cursor"] == "abc"


def test_an_unknown_status_is_rejected_before_dagster_is_asked(as_viewer):
    with patch("apps.runs.views.dagster.list_runs") as listed:
        response = as_viewer.get("/api/runs/?status=NOT_A_STATUS")

    assert response.status_code == 400
    listed.assert_not_called()


def test_a_limit_beyond_the_maximum_is_rejected(as_viewer):
    assert as_viewer.get("/api/runs/?limit=500").status_code == 400


def test_run_detail_carries_steps_and_the_failure_summary(as_viewer):
    detail = portal_run(status="FAILURE")
    detail["tags"] = [{"key": "user", "value": "admin-user"}]
    detail["steps"] = [
        {
            "step_key": "bronze_sync",
            "status": "FAILURE",
            "started_at": "2025-09-04T15:33:30+00:00",
            "ended_at": "2025-09-04T15:34:00+00:00",
            "duration_seconds": 30.0,
        }
    ]
    detail["failure_summary"] = "rclone exited 1"

    with patch("apps.runs.views.dagster.get_run", return_value=detail):
        response = as_viewer.get(f"/api/runs/{RUN_ID}")

    assert response.status_code == 200
    assert response.data["failure_summary"] == "rclone exited 1"
    assert response.data["steps"][0]["step_key"] == "bronze_sync"


def test_an_unknown_run_is_404(as_viewer):
    with patch("apps.runs.views.dagster.get_run", return_value=None):
        assert as_viewer.get(f"/api/runs/{RUN_ID}").status_code == 404


def test_logs_page_through_the_event_stream(as_viewer):
    page = {
        "events": [
            {
                "timestamp": "2025-09-04T15:33:30+00:00",
                "level": "ERROR",
                "step_key": "bronze_sync",
                "message": "step failed",
                "error": {"message": "rclone exited 1", "stack": ["line one"]},
            }
        ],
        "next_cursor": "c2",
        "has_more": True,
    }
    with patch("apps.runs.views.dagster.get_run_logs", return_value=page) as logs:
        response = as_viewer.get(f"/api/runs/{RUN_ID}/logs?cursor=c1&limit=50")

    assert response.status_code == 200
    assert response.data["has_more"] is True
    assert response.data["events"][0]["error"]["stack"] == ["line one"]
    assert logs.call_args.kwargs == {"cursor": "c1", "limit": 50}


def test_logs_for_an_unknown_run_are_404(as_viewer):
    with patch("apps.runs.views.dagster.get_run_logs", return_value=None):
        assert as_viewer.get(f"/api/runs/{RUN_ID}/logs").status_code == 404


# --- upstream failure ------------------------------------------------------


def test_an_unreachable_dagster_is_503_not_500(as_viewer):
    with patch("apps.runs.views.dagster.list_runs", side_effect=dagster.DagsterUnavailable("down")):
        response = as_viewer.get("/api/runs/")

    assert response.status_code == 503
    assert response.data["detail"] == "Dagster is unreachable"


def test_a_dagster_error_is_502(as_viewer):
    with patch("apps.runs.views.dagster.list_runs", side_effect=dagster.DagsterError("boom")):
        assert as_viewer.get("/api/runs/").status_code == 502


# --- triggering ------------------------------------------------------------


def test_a_viewer_may_not_trigger_a_run(as_viewer):
    with patch("apps.runs.views.dagster.launch_run") as launch:
        response = as_viewer.post("/api/runs/trigger")

    assert response.status_code == 403
    launch.assert_not_called()


def test_an_admin_launches_the_configured_job_and_gets_202(as_admin):
    with (
        patch("apps.runs.views.dagster.list_runs", return_value=[]),
        patch(
            "apps.runs.views.dagster.launch_run",
            return_value={"id": "new-run", "status": "QUEUED"},
        ) as launch,
    ):
        response = as_admin.post("/api/runs/trigger")

    assert response.status_code == 202
    assert response.data == {"id": "new-run", "status": "QUEUED"}
    # The job comes from settings; the client never chooses it.
    launch.assert_called_once_with("weekly_pipeline")


def test_a_second_launch_while_one_is_in_flight_is_409(as_admin):
    with (
        patch("apps.runs.views.dagster.list_runs", return_value=[portal_run(status="STARTED")]),
        patch("apps.runs.views.dagster.launch_run") as launch,
    ):
        response = as_admin.post("/api/runs/trigger")

    assert response.status_code == 409
    assert response.data["run_id"] == RUN_ID
    launch.assert_not_called()


def test_the_in_flight_guard_asks_about_unfinished_statuses_only(as_admin):
    with (
        patch("apps.runs.views.dagster.list_runs", return_value=[]) as listed,
        patch("apps.runs.views.dagster.launch_run", return_value={"id": "r", "status": "QUEUED"}),
    ):
        as_admin.post("/api/runs/trigger")

    asked = listed.call_args.kwargs["statuses"]
    assert "MANAGED" in asked
    assert "SUCCESS" not in asked


def test_an_unreachable_dagster_fails_the_trigger_with_503(as_admin):
    with patch("apps.runs.views.dagster.list_runs", side_effect=dagster.DagsterUnavailable("down")):
        assert as_admin.post("/api/runs/trigger").status_code == 503
