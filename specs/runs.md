# Pipeline Runs

Run data comes from Dagster via its GraphQL API only (docs/adr/004).
Role behaviour is in specs/auth.md. What the API talks to, and the quirks
it works around, are in context/integrations/dagster.md.

Built, except the log viewer.

## Run history

The Runs page lists the ingestion pipeline's runs, newest first: the run
id, its status, when it started, and how long it took. Selecting a run
opens it in place and shows its per-step detail — each step's name,
status and timing — along with what triggered the run and how many
assets it materialised. A failed run shows the reason it failed above
its steps.

Nothing is stored. Every request asks Dagster and shapes the answer, so
the portal holds no copy of the history to fall back on. When Dagster
cannot be reached the page says exactly that and offers to try again,
because the portal itself is working.

Dagster has more run states than the page has colours for. Canceled runs,
and any state a future Dagster adds, are shown named but in a muted
style rather than being forced into a colour that would misreport them.

## Refreshing

Run information updates only when the user asks for it. There is a
refresh control, and the page says how long ago it last read. There is
no background polling.

An earlier decision had the page poll itself while a run was active.
The design reversed it and states "Manual refresh only" on the page. The
pipeline runs weekly and its schedule ships stopped, so the list is
almost always one or two rows that do not change while anyone is looking
at them; polling would spend requests to report nothing.

## Triggering

An Admin can launch one full pipeline run, after an explicit
confirmation step; dismissing the confirmation launches nothing. The
portal never chooses what to run — the job is named in configuration and
the request carries no body.

If a run is already in progress the server refuses to launch another,
including against a direct API call. The button is also unavailable when
a run is in flight, when the list has not loaded yet, and when Dagster
did not answer — offering an action that cannot succeed is worse than
not offering it. A Viewer never sees the button, and is refused
server-side regardless.

## Not built

The event log. `GET /api/runs/{id}/logs` serves it and is tested, but no
screen reads it yet: the design has no log viewer. Filtering the list by
status, and paging beyond the most recent 25 runs, are also not built —
the API supports both.
