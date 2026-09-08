# CLAUDE.md — Geo Portal

Internal web app over the geospatial knowledge base: Ask (cross-source
Q&A), Map (results, footprints, area-scoped questions), Runs (Dagster).
The data platform repo populates the knowledge base; this repo reads it.

## Communication

How to write every message, in chat and in the repo:

- **Simple English.** Short sentences. Common words, not rare ones.
- **Brief.** Say the thing, then stop. No preamble, no recap of what
  the reader already knows.
- **Never cryptic.** Say what you mean outright. No hinting, no
  wordplay, no leaving the point to be inferred.
- **Define your terms.** The first time a name, acronym, file, flag,
  table or column appears, say in a few words what it is.
- **Clear over clever.** Plain phrasing beats style every time.

## Non-negotiables

Changing any of these is a decision worth an ADR.

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
  `frontend/src/styles/tokens.css` is data, not source: never reformat it
  (formatters flatten the trailing zeros that document the tonal ladder).
- Secrets by name (`DATABASE_URL`), never by value — in code, logs,
  prompts, and diary entries. Chat content stays in `portal`, never in
  application logs.
- Do not invent endpoints, tables, or tools; if something needed is
  missing, stop and ask.

## Where things live

- `context/` — how the system is now (overview, architecture, standards,
  UI rules, design system, ui-registry, integrations/)
- `specs/` — what has been built, in plain prose; each file says what
  is built and what is not
- `docs/adr/` — decisions, append-only, superseded never edited
- `diary/` — session log, append-only; latest entry only on restore
- Jira — the features to build, and their status

## Integration docs & skills

- context/integrations/ — one file per technology as built. `kb.md` is
  the knowledge base's schema and access rules.
