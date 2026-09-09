# Pipeline Runs

Run data comes from Dagster via its GraphQL API only (docs/adr/004).
Role behaviour is in specs/auth.md.

Not built.

## Run history

The Runs page shows the ingestion pipeline's run history — each run's
status, start time and duration, newest first. Selecting a run shows its
per-step detail: each step's name, status and timing, and for a failed
step, the failure reason.

## Refreshing

Run information updates only when the user asks for it. There is no
background polling, so a run finishing in Dagster leaves the page
unchanged until a refresh.

## Triggering

An Admin can launch one full pipeline run, after an explicit confirmation
step; the new run then appears in the list. Dismissing the confirmation
launches nothing. If a run is already in progress the server refuses to
launch another, including against a direct API call.
