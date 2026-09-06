# ADR-002: Two Postgres databases in one instance

**Status:** Accepted · 2026-09-01

## Context

The knowledge base (STAC metadata, pgvector embeddings, document chunks,
dataset cards) lives in Postgres and is owned by the data platform repo.
Geo Portal needs its own relational state (users, chat sessions, messages,
saved areas). Both can share one Postgres instance; the question was one
database with two schemas vs. two databases.

## Decision

Two databases in the same instance: `kb` (platform repo) and `portal`
(this repo). The portal's role is **read-only on `kb`** and read-write on
`portal`. Each repo owns its own database's migration history.

## Why

- The boundary matches repo ownership: two codebases deploy independently
  with independent migration histories — no shared migration state.
- Permissions are structural, not conventional: a bad portal migration
  cannot touch the knowledge base.
- The classic cost of separate databases — no cross-database SQL joins —
  barely applies: portal state joins with KB content in application code.
- Extensions are per-database: pgvector stays in `kb`; `portal` stays
  vanilla.

## Rejected

**One database, two schemas** — allows cross-schema joins and a single
connection, but mixes two repos' migrations in one database and makes the
read-only boundary a matter of discipline instead of grants.

## Revisit when

Portal features need SQL joins against KB tables — e.g. user annotations
on assets queried jointly with asset metadata. That is the trigger to
write the superseding ADR (schemas, or postgres_fdw).
