# Pipeline Runs

Run data comes from Dagster via its GraphQL API only (docs/adr/004).
Role behaviour is in specs/auth.md. What the API is talking to, and the
quirks it works around, are in context/integrations/dagster.md.

The API is built. The Runs page is not.

## Run history

The API serves the ingestion pipeline's run history — each run's status,
start time and duration, newest first, filtered by status or job and read
a page at a time. One run also carries its per-step detail: each step's
name, status and timing, and for a failed run, the reason it failed.

A run's event log is read separately and a page at a time, because a log
can be long and is only wanted when someone opens a run.

Nothing is stored. Every request asks Dagster and shapes the answer, so
the portal holds no copy of the run history to fall back on. When Dagster
cannot be reached the API says so plainly — a portal that is working fine
in front of an orchestrator that is not.

## Refreshing

The page will refresh itself while a run is going, and stop once nothing
is running. This replaces the earlier decision that runs updated only
when asked for; the reason is that a run people are watching changes
state on its own, and a page that lies until clicked is worse than one
that polls briefly. Not built yet, and it needs an ADR when it is.

## Triggering

An Admin can launch one full pipeline run. The portal never chooses what
to run: the job is named in configuration, and the request carries no
body at all. If a run is already in progress the server refuses to launch
another, including against a direct API call. A Viewer calling the
endpoint directly is refused as well.

The confirmation step before launching belongs to the page, which is not
built. Dismissing it will launch nothing.

## What the page will add

The run list, the per-step detail view, the log viewer, and the trigger
button. None of it exists yet.
