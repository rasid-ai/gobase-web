"""The only module that speaks Dagster's GraphQL API.

Everything above this speaks in portal terms: ISO timestamps, a named trigger,
a duration in seconds. The schema this maps onto, and the quirks it works
around, are in context/integrations/dagster.md; docs/adr/004 explains why the
GraphQL API is the only way in and why `launchRun` is the only write.

Plain HTTP rather than the `dagster-graphql` package: that package has no
public method for an arbitrary query like `runsOrError`, so using it would mean
depending on its internals to avoid depending on Dagster's.
"""

import logging
from datetime import UTC, datetime

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# The nine values of Dagster's RunStatus enum. MANAGED is easy to miss and
# belongs with the unfinished ones: the launch guard would rather refuse a
# legitimate run than start a second copy of a 1TB sync.
IN_PROGRESS_STATUSES = ("QUEUED", "NOT_STARTED", "MANAGED", "STARTING", "STARTED")
TERMINAL_STATUSES = ("SUCCESS", "FAILURE", "CANCELING", "CANCELED")
RUN_STATUSES = IN_PROGRESS_STATUSES + TERMINAL_STATUSES

# A failed step's message is only in the event log, which cannot be filtered or
# read backwards. So the scan pages forward and stops at the first error. This
# caps what one detail request may read when a run failed late or not at all.
_FAILURE_SCAN_PAGE = 1000
_FAILURE_SCAN_MAX_PAGES = 5


class DagsterUnavailable(Exception):
    """Dagster could not be reached at all: refused, unresolved, or too slow."""


class DagsterError(Exception):
    """Dagster answered, but with an error branch instead of the data."""


_RUN_FIELDS = """
    runId jobName status creationTime startTime endTime
    tags { key value }
    assetSelection { path }
    stats {
      __typename
      ... on RunStatsSnapshot { stepsSucceeded stepsFailed materializations }
      ... on PythonError { message }
    }
"""

_LIST_RUNS = (
    """
query Runs($filter: RunsFilter, $cursor: String, $limit: Int) {
  runsOrError(filter: $filter, cursor: $cursor, limit: $limit) {
    __typename
    ... on Runs { results {
"""
    + _RUN_FIELDS
    + """
    } }
    ... on InvalidPipelineRunsFilterError { message }
    ... on PythonError { message }
  }
}
"""
)

_GET_RUN = (
    """
query Run($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run {
"""
    + _RUN_FIELDS
    + """
      stepStats { stepKey status startTime endTime }
    }
    ... on RunNotFoundError { message }
    ... on PythonError { message }
  }
}
"""
)

_GET_LOGS = """
query Logs($runId: ID!, $afterCursor: String, $limit: Int) {
  logsForRun(runId: $runId, afterCursor: $afterCursor, limit: $limit) {
    __typename
    ... on EventConnection {
      cursor
      hasMore
      events {
        __typename
        ... on MessageEvent { message timestamp level stepKey }
        ... on ErrorEvent { error { message stack } }
      }
    }
    ... on RunNotFoundError { message }
    ... on PythonError { message }
  }
}
"""

# Three of launchRun's twelve branches -- RunConfigValidationInvalid,
# InvalidStepError and InvalidOutputError -- carry no `message` field, so asking
# for one makes the whole document invalid. They are left out: _branch falls
# back to naming the branch, which is enough for a case the portal cannot cause
# anyway, since it sends no run config and no step selection.
_LAUNCH_RUN = """
mutation Launch($executionParams: ExecutionParams!) {
  launchRun(executionParams: $executionParams) {
    __typename
    ... on LaunchRunSuccess { run { runId status } }
    ... on RunConflict { message }
    ... on PipelineNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on InvalidSubsetError { message }
    ... on PresetNotFoundError { message }
    ... on ConflictingExecutionParamsError { message }
    ... on NoModeProvidedError { message }
    ... on PythonError { message }
  }
}
"""


def _post(query: str, variables: dict) -> dict:
    """Send one GraphQL document and return its `data`, or raise."""
    try:
        response = httpx.post(
            settings.DAGSTER_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=settings.DAGSTER_TIMEOUT_SECONDS,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise DagsterUnavailable(str(exc)) from exc

    # The body is read before the status code on purpose. Dagster answers a
    # rejected query -- a bad enum value, say -- with HTTP 500 and a proper
    # GraphQL `errors` body. That is Dagster answering, not Dagster being down,
    # and calling it unreachable would report an outage that is not happening.
    try:
        payload = response.json()
    except ValueError:
        raise DagsterUnavailable(
            f"Dagster returned HTTP {response.status_code} and no JSON"
        ) from None

    if payload.get("errors"):
        raise DagsterError(payload["errors"][0].get("message", "Unknown GraphQL error"))
    if response.status_code >= 400:
        raise DagsterUnavailable(f"Dagster returned HTTP {response.status_code}")
    return payload.get("data") or {}


def _branch(data: dict, field: str, expected: str) -> dict | None:
    """Dispatch one union response.

    Every Dagster query answers 200 with a `__typename` naming the branch, so
    this is where an error becomes an exception. `RunNotFoundError` returns
    None instead: a missing run is an answer, not a failure, and the view turns
    it into a 404 the way apps/map/views.py does.
    """
    result = data.get(field) or {}
    typename = result.get("__typename")
    if typename == expected:
        return result
    if typename == "RunNotFoundError":
        return None
    raise DagsterError(result.get("message") or f"Dagster returned {typename}")


def _seconds_to_iso(value) -> str | None:
    """Dagster's Float seconds since the epoch, as ISO 8601 UTC."""
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat()


def _millis_to_iso(value) -> str | None:
    """An event's timestamp: a *string* of milliseconds, unlike every other time."""
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()


def _trigger(tags: dict) -> dict:
    """What started the run. Dagster does not say outright; the tags do."""
    if "dagster/schedule_name" in tags:
        return {"kind": "schedule", "name": tags["dagster/schedule_name"]}
    if "dagster/sensor_name" in tags:
        return {"kind": "sensor", "name": tags["dagster/sensor_name"]}
    return {"kind": "manual", "name": tags.get("user")}


def _run(node: dict) -> dict:
    """One Dagster run in portal terms."""
    tags = {tag["key"]: tag["value"] for tag in node.get("tags") or []}
    started, ended = node.get("startTime"), node.get("endTime")
    stats = node.get("stats") or {}
    # `stats` is itself a union; a PythonError there must not lose the run.
    if stats.get("__typename") != "RunStatsSnapshot":
        stats = {}

    run_id = node["runId"]
    return {
        "id": run_id,
        "short_id": run_id[:8],
        "job_name": node.get("jobName"),
        "status": node.get("status"),
        "created_at": _seconds_to_iso(node.get("creationTime")),
        "started_at": _seconds_to_iso(started),
        "ended_at": _seconds_to_iso(ended),
        "duration_seconds": (ended - started) if started and ended else None,
        "trigger": _trigger(tags),
        "partition": tags.get("dagster/partition"),
        "steps_succeeded": stats.get("stepsSucceeded"),
        "steps_failed": stats.get("stepsFailed"),
        "materializations": stats.get("materializations"),
        "assets": ["/".join(key["path"]) for key in node.get("assetSelection") or []],
    }


def _step(node: dict) -> dict:
    """One step of a run. Its status enum is StepEventStatus, not RunStatus."""
    started, ended = node.get("startTime"), node.get("endTime")
    return {
        "step_key": node.get("stepKey"),
        "status": node.get("status"),
        "started_at": _seconds_to_iso(started),
        "ended_at": _seconds_to_iso(ended),
        "duration_seconds": (ended - started) if started and ended else None,
    }


def _event(node: dict) -> dict:
    """One log event. `error` is present only on the two failure event types."""
    error = node.get("error")
    return {
        "timestamp": _millis_to_iso(node.get("timestamp")),
        "level": node.get("level"),
        "step_key": node.get("stepKey"),
        "message": node.get("message"),
        "error": {"message": error["message"], "stack": error.get("stack") or []}
        if error
        else None,
    }


def list_runs(statuses=None, job_name=None, limit=25, cursor=None) -> list[dict]:
    """Runs newest first. `cursor` is the previous page's last run id."""
    run_filter = {}
    if statuses:
        run_filter["statuses"] = list(statuses)
    if job_name:
        # RunsFilter has no jobName key, only pipelineName — even though the
        # field that comes back on a Run is jobName.
        run_filter["pipelineName"] = job_name

    data = _post(_LIST_RUNS, {"filter": run_filter or None, "cursor": cursor, "limit": limit})
    runs = _branch(data, "runsOrError", "Runs")
    return [_run(node) for node in runs["results"]]


def get_run(run_id: str) -> dict | None:
    """One run with its per-step breakdown, or None if there is no such run."""
    data = _post(_GET_RUN, {"runId": run_id})
    node = _branch(data, "runOrError", "Run")
    if node is None:
        return None

    detail = _run(node)
    detail["tags"] = node.get("tags") or []
    detail["steps"] = [_step(step) for step in node.get("stepStats") or []]
    detail["failure_summary"] = _first_failure(run_id) if detail["status"] == "FAILURE" else None
    return detail


def get_run_logs(run_id: str, cursor=None, limit=200) -> dict | None:
    """A page of the event log, or None if there is no such run."""
    data = _post(_GET_LOGS, {"runId": run_id, "afterCursor": cursor, "limit": limit})
    page = _branch(data, "logsForRun", "EventConnection")
    if page is None:
        return None
    return {
        "events": [_event(event) for event in page["events"]],
        "next_cursor": page["cursor"],
        "has_more": page["hasMore"],
    }


def _first_failure(run_id: str) -> str | None:
    """The first error message in a failed run's log.

    The log cannot be filtered or read backwards, so this pages forward and
    stops at the first error. The page cap keeps one detail request bounded on
    a run that failed very late; hitting it means no summary, not an error.
    """
    cursor = None
    for _ in range(_FAILURE_SCAN_MAX_PAGES):
        page = get_run_logs(run_id, cursor=cursor, limit=_FAILURE_SCAN_PAGE)
        if page is None:
            return None
        for event in page["events"]:
            if event["error"]:
                return event["error"]["message"]
        if not page["has_more"]:
            return None
        cursor = page["next_cursor"]

    logger.warning(
        "Gave up looking for the failure of run %s after %d pages", run_id, _FAILURE_SCAN_MAX_PAGES
    )
    return None


def launch_run(job_name: str) -> dict:
    """Start one run of `job_name`. The only write the portal ever makes."""
    data = _post(
        _LAUNCH_RUN,
        {
            "executionParams": {
                "selector": {
                    "jobName": job_name,
                    "repositoryName": settings.DAGSTER_REPOSITORY,
                    "repositoryLocationName": settings.DAGSTER_REPOSITORY_LOCATION,
                }
            }
        },
    )
    launched = _branch(data, "launchRun", "LaunchRunSuccess")
    return {"id": launched["run"]["runId"], "status": launched["run"]["status"]}
