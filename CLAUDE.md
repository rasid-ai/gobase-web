# CLAUDE.md — Geo Portal

Internal web app over the geospatial knowledge base: Ask (cross-source
Q&A), Map (results, footprints, area-scoped questions), Runs (Dagster).
The data platform repo populates the knowledge base; this repo reads it.

## Non-negotiables

Changing any of these requires an ADR.

- The portal reads the knowledge base (`kb` database, S3 buckets) and
  never writes it. Read-only credentials enforce this. See context/architecture.md.
- Two Postgres databases, one instance: `kb` (read-only) and `portal`
  (ours). Never run migrations against `kb`. See docs/adr/002.
- Mirror the Rainbow reference stack: DRF backend, Vite+React+TS SPA. See docs/adr/001.
- `backend/openapi.yaml` is the only backend↔frontend contract. The
  frontend client is Orval-generated from it, never hand-written.
- The frontend never talks to S3, DuckDB, Dagster, or any LLM, and never
  computes an answer — it renders what the API returns.
- Agent-issued SQL is SELECT-only, rejected before execution.
- Dagster only via its GraphQL API; the sole mutation is `launchRun`,
  Admin-only. See docs/adr/004.
- MapLibre GL, not Leaflet. See docs/adr/003.
- Every factual answer about the data cites asset UUIDs from the catalog.
- Design tokens only — never hardcode hex or raw Tailwind color classes.
- Secrets by name (`DATABASE_URL`), never by value — in code, logs,
  prompts, and diary entries. Chat content stays in `portal`, never in
  application logs.
- Do not invent endpoints, tables, or tools; if something needed is
  missing, stop and ask.

## Where things live

- `context/` — how the system is now (overview, architecture, standards,
  UI rules, design system, ui-registry, integrations/)
- `specs/` — requirements: IDs, EARS wording, done criteria
- `docs/adr/` — decisions, append-only, superseded never edited
- `diary/` — session log, append-only; latest entry only on restore
- Jira — status. No markdown file claims "done" or "in progress".

## Integration docs & skills

- context/integrations/ — none yet; add one file per technology as built.
