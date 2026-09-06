# ADR-001: Adopt the Rainbow Ltd reference architecture

**Status:** Accepted · 2026-09-01

## Context

Geo Portal needs a full-stack shape: API framework, contract mechanism,
SPA stack, auth pattern, deploy pipeline. The team has already built and
operated Rainbow Ltd on a specific combination and knows its failure
modes.

## Decision

Mirror the Rainbow Ltd architecture: Django REST Framework over Postgres;
drf-spectacular exports `openapi.yaml` in CI as the versioned contract;
Orval generates the typed frontend client from it; JWT auth via simplejwt
(access in memory, refresh in httpOnly cookie), roles on a `UserProfile`
one-to-one managed through stock Django admin; Vite + React + TypeScript
SPA with shell + nested routes, TanStack Query/Table, Radix + shadcn +
Tailwind (tokens only); pytest / Vitest; GitHub Actions → GHCR → SSH
`deploy.sh` with docker compose on a VPS, Postgres native on the host,
nginx same-origin routing.

## Rejected

- **FastAPI** — better native async/SSE ergonomics, but loses the proven
  auth/admin/deploy template and adds a second backend idiom to maintain
  across the two projects. SSE works under Django served via ASGI.
- **Next.js** — internal, authenticated, nothing public or SEO-facing; a
  plain SPA is simpler to build and deploy as a static container.

## Revisit when

Chat streaming or agent concurrency measurably outgrows Django-on-ASGI —
that would reopen FastAPI for the chat service only, not the whole stack.
