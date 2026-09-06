# Spec: Pipeline Runs

Run data comes from Dagster via its GraphQL API only (docs/adr/004).
Role gating is HLR-006 (specs/auth.md).

---

**HLR-009** — The system SHALL show the ingestion pipeline's run history:
each run's status, start time, and duration, newest first.
Priority: Must · Phase: MVP
**Done means:**
GIVEN Dagster holds completed and failed runs
WHEN the Runs page loads
THEN every run appears newest-first with its status, start time, and
duration

---

**HLR-010** — WHEN a run is selected, the system SHALL show its per-step
detail: each step's name, status, timing, and — for a failed step — the
failure reason.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a run in which one step failed
WHEN that run is opened
THEN every step is listed with status and timing
AND the failed step shows its failure reason

---

**HLR-011** — The system SHALL update run information only when the user
requests a refresh; there is no background polling.
Priority: Must · Phase: MVP
**Done means:**
GIVEN the Runs page is open
WHEN a run finishes in Dagster
THEN the page is unchanged until the user refreshes
AND WHEN the user refreshes
THEN the new state appears

---

**HLR-012** — WHEN an Admin requests a pipeline run and explicitly
confirms, the system SHALL launch one full pipeline run and show it in
the run list.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a signed-in Admin and no active run
WHEN they trigger and confirm
THEN exactly one run is launched and appears in the list
AND WHEN they trigger but dismiss the confirmation
THEN no run is launched

---

**HLR-013** — IF a pipeline run is already in progress, THEN the system
SHALL refuse to launch another, enforced server-side.
Priority: Must · Phase: MVP
**Done means:**
GIVEN an active run
WHEN an Admin confirms a trigger (including by direct API call)
THEN the response is an error and no second run exists in Dagster
