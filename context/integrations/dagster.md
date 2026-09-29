# Dagster — run history and the manual trigger

Dagster is the orchestrator that runs the weekly ingestion pipeline. It
lives in the sibling data platform repo (`../gobase`), not here. The
portal reads run information from it and can ask it to start a run; it
never reads Dagster's own database (docs/adr/004).

Everything below was read off a live server, not assumed. Dagster 1.13.19.

## Connecting

`POST {DAGSTER_GRAPHQL_URL}/` — one endpoint, GraphQL only, served by
`dagster-webserver`. There is **no authentication**: the webserver binds
to `127.0.0.1:3000` and is reached over an SSH tunnel. Nothing but the
portal backend may talk to it, and the frontend never does.

Settings, all named in `backend/.env.example` and `infra/.env.example`:

| Setting | Local default | What it is |
|---|---|---|
| `DAGSTER_GRAPHQL_URL` | `http://127.0.0.1:3000/graphql` | The GraphQL endpoint. In production the backend runs in Docker and Dagster does not, so the deployed value is `http://host.docker.internal:3000/graphql`. |
| `DAGSTER_REPOSITORY_LOCATION` | `gobase_orchestration.definitions` | The code location name. It is the module path, because the server is started with `dagster dev -m gobase_orchestration.definitions`. |
| `DAGSTER_REPOSITORY` | `__repository__` | The repository name. The pipeline uses modern `Definitions`, which has no named repository, so Dagster generates this one. |
| `DAGSTER_JOB_NAME` | `weekly_pipeline` | The one job the portal may launch. |
| `DAGSTER_TIMEOUT_SECONDS` | `5` | Per-request timeout. |

Confirm the location and repository names on a new server before trusting
them — they change if the pipeline is loaded a different way:

```graphql
{ repositoriesOrError { ... on RepositoryConnection {
    nodes { name location { name } pipelines { name } } } } }
```

## The job

`weekly_pipeline` runs all five assets: `bronze_sync`, `silver_vector`,
`silver_raster`, `silver_tabular`, `catalog_ingest`. Its schedule is
Saturday 02:00 Asia/Beirut and it **ships stopped**, to be armed by hand
after the first full sync — so today a manual trigger is the only way a
run starts.

The repository also lists a job called `__ASSET_JOB`. That is Dagster's
own implicit job, not ours; every read filters on `DAGSTER_JOB_NAME`.

**`weekly_pipeline` starts with `bronze_sync`, an rclone transfer the
pipeline repo warns can be about 1TB. Never launch it to try something
out.**

## The four operations

All of them live in `backend/apps/runs/dagster.py` and nowhere else.

| Portal call | GraphQL |
|---|---|
| `list_runs` | `runsOrError(filter: RunsFilter, cursor: String, limit: Int)` |
| `get_run` | `runOrError(runId: ID!)` |
| `get_run_logs` | `logsForRun(runId: ID!, afterCursor: String, limit: Int)` |
| `launch_run` | `launchRun(executionParams: ExecutionParams!)` |

`RunsFilter` takes `statuses` and `pipelineName` (there is no `jobName`
key on the filter, despite `Run.jobName` being the field that comes back).

`launchRun`'s selector is
`{ jobName, repositoryName, repositoryLocationName }`. The portal sends no
run config at all, so `runConfigData` is omitted.

## Every response is a union

There is no HTTP error to check. A GraphQL call returns 200 with a
`__typename` naming which branch came back, so every response is
dispatched on it:

| Query | Branches |
|---|---|
| `runsOrError` | `Runs`, `InvalidPipelineRunsFilterError`, `PythonError` |
| `runOrError` | `Run`, `RunNotFoundError`, `PythonError` |
| `logsForRun` | `EventConnection`, `RunNotFoundError`, `PythonError` |
| `launchRun` | `LaunchRunSuccess` plus eleven error branches, including `RunConflict`, `UnauthorizedError`, `PipelineNotFoundError`, `PythonError` |

## Quirks that will bite

- **Run statuses are nine, not eight.** `QUEUED`, `NOT_STARTED`,
  `MANAGED`, `STARTING`, `STARTED`, `SUCCESS`, `FAILURE`, `CANCELING`,
  `CANCELED`. `MANAGED` is easy to miss.
- **Step statuses are a different, smaller enum** (`StepEventStatus`):
  `SKIPPED`, `SUCCESS`, `FAILURE`, `IN_PROGRESS`. A step is never
  "queued" and never "canceled".
- **Time is two different types.** `Run.creationTime`, `startTime`,
  `endTime` and `RunStepStats.startTime`/`endTime` are `Float` seconds
  since the epoch. But an event's `timestamp` is a **`String`** of
  milliseconds. Both become ISO 8601 UTC before leaving the backend.
- **The log cursor argument is `afterCursor`**, not `cursor` — unlike
  `runsOrError`, which does use `cursor`.
- **`PythonError.stack` is a list of strings**, not one string.
- **Three of `launchRun`'s twelve branches have no `message` field**:
  `RunConfigValidationInvalid`, `InvalidStepError` and `InvalidOutputError`.
  Asking for one does not fail that branch — it makes the whole document
  invalid, so every launch fails with a confusing parse error. They are
  left out of the query and named by `__typename` instead.
- **Both failure events implement `ErrorEvent`**, so
  `... on ErrorEvent { error { message stack } }` catches
  `ExecutionStepFailureEvent` and `RunFailureEvent` in one spread.
- **Per-step detail comes from `Run.stepStats`**, which gives `stepKey`,
  `status`, `startTime` and `endTime` directly. It does not have to be
  derived from the event log.
- **`EventConnection` already returns `cursor` and `hasMore`**, so log
  pagination is passed through rather than computed.

## How a run's trigger is known

Dagster does not label what started a run. It is read from the run's tags:
`dagster/schedule_name` means a schedule, `dagster/sensor_name` means a
sensor, and anything else is a manual launch.

## State of the local setup

Nothing is running by default. To bring it up, from `../gobase`:

```
DAGSTER_HOME=$PWD/.dagster_home .venv/bin/dagster dev \
    -m gobase_orchestration.definitions -h 127.0.0.1 -p 3000
```

There is no run history in a fresh `DAGSTER_HOME`, so `runsOrError`
returns an empty list rather than an error. The portal treats that as an
empty page, not a failure.

To make one cheap run without moving data, ask Dagster directly for a
single asset — `catalog_ingest` finds nothing to catalogue when object
storage is down, and succeeds in a few seconds:

```json
{"selector": {"jobName": "weekly_pipeline",
              "repositoryName": "__repository__",
              "repositoryLocationName": "gobase_orchestration.definitions",
              "assetSelection": [{"path": ["catalog_ingest"]}]}}
```

The portal itself cannot do this, by design: `launch_run` sends no asset
selection, so the only thing it can start is the whole job.
