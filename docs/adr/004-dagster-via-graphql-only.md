# ADR-004: Dagster is reached only via its GraphQL API

**Status:** Accepted · 2026-09-01

## Context

The Runs page shows ingestion pipeline run status/history, and Admins can
trigger a full pipeline run. Dagster (in the platform repo) stores run
state in its own Postgres database, which we could technically read
directly.

## Decision

The portal backend talks to Dagster exclusively through the Dagster
GraphQL API. Reads (run list, run detail, logs) serve both roles; the
**only mutation the portal ever sends is `launchRun`**, exposed as
`POST /api/runs/trigger/`, Admin-only.

## Why

- Dagster's internal schema is not a public contract; the GraphQL API is.
  Reading internal tables would couple this repo to the platform repo's
  Dagster version and block its upgrades.
- Confining mutations to one named operation keeps the portal's
  "reads the knowledge base, never writes it" boundary honest: the portal
  asks Dagster to run; Dagster writes.

## Rejected

**Reading Dagster's Postgres directly** — one less network hop, no API
surface to learn, but couples two repos through a private schema.

## Revisit when

Run-history queries outgrow what the GraphQL API answers efficiently
(e.g. cross-run analytics). That would justify a read-only reporting
view exported deliberately by the platform repo — still not raw internal
tables.
