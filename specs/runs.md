# Pipeline Runs

Run data comes from Dagster via its GraphQL API only (docs/adr/004).
Role behaviour is in specs/auth.md. What the API talks to, and the quirks
it works around, are in context/integrations/dagster.md.

Built.

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

## The event log

A run's event log is read separately, a page at a time, and only when
someone asks for it: opening a run shows its steps, and the log sits
behind one more click. A log is hundreds of lines that matter only when
something went wrong, so nothing is fetched until it is wanted.

The log is filtered by minimum level and starts at info. Dagster writes
most of a run at debug level — fourteen of the first real run's eighteen
events — so showing everything by default would bury the four lines that
say what happened. The page says how many lines the current level hides,
and debug is one click away. An event carrying an error can be expanded
to its stack.

## Filtering and paging

The list filters by status, grouped into the four states worth asking
about: running, success, failed, canceled. Nothing selected means
everything, and the API is then asked for everything. A filter that
matches nothing says so, rather than claiming there are no runs.

The list loads twenty-five runs at a time and keeps what it has when it
asks for more. At one run a week, that first page is roughly six months.
