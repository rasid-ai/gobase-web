# Architecture

## Stack

**Geo Portal** is an internal, API-first web application — the query-side
companion to the data platform repo. The platform repo ingests files and
populates the knowledge base; this repo reads that knowledge base and never
writes it. Single **mono-repo** with `/backend`, `/frontend`, and `/infra`
at the root, deployed as two containers via one shared deploy script.

**Backend:** Django REST Framework over PostgreSQL is the single source of
truth for all portal state and all query composition; the client never
composes a query, calls a model, or touches a store directly.

**Postgres layout — two databases, one instance:**

| Database | Owner | Portal access | Contents |
|---|---|---|---|
| `kb` | data platform repo | **read-only role** | STAC metadata, document chunks, pgvector embeddings, dataset cards, asset catalog |
| `portal` | this repo | read-write | users/profiles, chat sessions and messages, saved areas, citations |

Migrations for `portal` run via Django's migration system; `kb` migrations
belong to the platform repo and are never run from here. See docs/adr/001.

**Data engines (all read-only against the knowledge base):**

- **pgvector** similarity search in `kb` for document chunks and dataset cards.
- **Embedded DuckDB** in the backend process queries Parquet/GeoParquet on
  S3 via httpfs — per-request connections, S3 credentials scoped read-only.
- **Dagster GraphQL API** is the only way run information is read. The
  backend never reads Dagster's internal database, so the platform repo can
  upgrade Dagster freely.

**Q&A engine:** what is settled regardless of engine choice: answers are
composed **server-side** across sources (documents, tabular, imagery
metadata); every data access is read-only and SQL is SELECT-only; a
drawn-area geometry scopes retrieval via H3/bbox; answers **stream** to
the SPA via SSE; citations reference asset UUIDs and persist with the
message in `portal`, along with the tool/query trace. **The engine itself
— LLM provider and agent/orchestration design — is still undecided**, and
gets its own ADR before the chat app is built.

**Auth:** JWT via `djangorestframework-simplejwt` (access token in memory,
refresh token in an httpOnly Secure cookie, fetch interceptor refreshes on
401). Two roles on `accounts.UserProfile` (one-to-one onto Django `User`,
managed from stock Django admin): **Admin** and **Viewer**.
`GET /api/auth/me` returns `{username, role}` so the SPA gates routes
without decoding the JWT.

Endpoint surface, all under `/api/auth/`:

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST login` | public | Credentials in; access token in the body, refresh token set as the cookie. |
| `POST refresh` | public | Reads the refresh **cookie** (never the body), rotates it, returns a new access token. |
| `POST logout` | required | Blacklists the refresh token and clears the cookie. |
| `GET me` | required | `{username, role}`. |
| `POST change-password` | required | Current + new password. |

One endpoint sits outside `/api/auth/`: `GET /api/health/`, public and
unauthenticated, checking `portal` connectivity only. `infra/deploy.sh` blocks
on it through nginx, so a green deploy means TLS, routing and the app all
work. `kb` is never probed — a knowledge base outage must not fail a portal
deploy.

Refresh rotation is on with blacklist-after-rotation, so a replayed cookie
is rejected — that is what makes a revoked session real rather than
advisory. The cookie is `HttpOnly`, `SameSite=Lax`, scoped to
`Path=/api/auth`, and `Secure` everywhere but local http. DRF's default
permission is `IsAuthenticated`, so a new endpoint is protected unless it
explicitly opts out.

**API contract:** drf-spectacular (OpenAPI 3); CI exports `openapi.yaml`
into the repo as the versioned contract; the frontend generates its typed
client and TanStack Query hooks from that same file via **Orval**, so
backend and frontend cannot drift.

**Frontend:** a single-page app — **Vite + React + TypeScript**. Shell +
nested routes (persistent sidebar layout) wrapping the two screens:

- **Map** — the main workspace: chat panel + map together. Chat is SSE
  streamed with citations linked to assets. The map is **MapLibre GL**
  (via react-map-gl) with **terra-draw** for rectangular area selection;
  it renders result GeoJSON layers, asset footprints on click, and
  "ask about this area". Raster tile display is a later phase.
- **Runs** — Dagster run list/detail via **TanStack Table**, manual
  refresh only. Admin additionally sees a "trigger pipeline run" action
  (Viewer does not). Theme: light and dark, user-toggled, tokens-driven.

Styling: **Tailwind CSS + shadcn/ui (Radix primitives)**, design tokens
only. Forms (where they exist): React Hook Form + Zod. Server state:
TanStack Query throughout.

**Deploy:** one **GitHub Actions** pipeline builds both images, pushes to
**GHCR** (`latest` + commit SHA), SSHes into the target VPS and runs
`deploy.sh` (`docker compose pull && up -d` against
`infra/docker-compose.prod.yml`). Two environments, selected by branch:
**`main` → the firm's VPS (production)** and **`dev` → the developer VPS
(development)**, same pipeline and script, different host secrets.
**PostgreSQL runs natively on each VPS host**, not containerized. **nginx
on the host** terminates TLS and routes four prefixes: `/` → frontend
container, and `/api`, `/admin/`, `/django-static/` → backend container —
same-origin in both environments, CORS is local-dev only. Django admin is
served in production because role assignment has no other UI, with its static
files carried inside the backend image by WhiteNoise (docs/adr/007).

The backend image runs gunicorn with uvicorn workers — ASGI from the start, so
SSE needs no change to the image — and applies `portal` migrations from its own
entrypoint, so an image and the schema it expects always ship together. CI
copies `infra/` onto the host each deploy; the host's `.env` is never touched.
A second workflow, `ci.yml`, gates pull requests on lint, tests, and drift in
both `openapi.yaml` and the generated client. `deploy.yml` calls it before
building, so a direct push is checked too.

**Testing:** pytest + pytest-django (backend), Vitest + React Testing
Library (frontend). **Tooling:** pnpm, Node 22 LTS, Python 3.12; pin
exact versions.

## Folder structure (mono-repo)

```text
geo-portal/
  backend/                 # Django REST Framework project
    config/                # settings, urls, asgi (SSE requires ASGI serving)
    apps/
      accounts/            # JWT auth, UserProfile (admin|viewer)
      chat/                # sessions, messages, agent loop, SSE streaming
      map/                 # footprint/coverage + asset metadata endpoints
      runs/                # Dagster GraphQL client, run list/detail
    openapi.yaml           # exported schema (the contract), committed in CI
    Dockerfile
  frontend/                # Vite + React + TypeScript SPA
    src/
      api/                 # Orval-generated client + TanStack Query hooks
      app/                 # shell, routing, providers
      features/            # workspace/ (map+chat)  runs/
      components/ui/       # shadcn/ui primitives
      lib/
    Dockerfile
  infra/
    docker-compose.prod.yml
    deploy.sh
    .env.example           # host environment, by name only
    README.md              # one-time VPS setup: nginx, Postgres, secrets
  docker-compose.dev.yml   # local dev, built from the same Dockerfiles
  .github/workflows/       # ci.yml (PR gate) + deploy.yml (build -> GHCR -> SSH)
```

## System boundaries

- The knowledge base (the `kb` database and the S3 bronze/silver buckets)
  is owned by the data platform repo. This backend **reads it and never
  writes it** — enforced by the read-only Postgres role and read-only S3
  credentials, not by convention.
- Backend owns all portal state, all query composition, and all LLM calls.
- Frontend is a pure consumer of the API. It never talks to S3, DuckDB,
  Dagster, or the LLM, and computes nothing beyond display.
- Dagster is reached only through its GraphQL API. Reads are open to both
  roles; the one mutation the portal ever sends is **launch pipeline run**,
  Admin-only. The portal still never writes data itself — Dagster does.
- The OpenAPI schema is the only contract between backend and frontend.

## Data flow

1. **Ask:** user message → `POST /api/chat/sessions/{id}/messages/` → agent
   loop calls tools (pgvector / DuckDB / STAC) → tokens stream back via SSE
   → completed message + tool trace + citations persist in `portal`.
2. **Map:** viewport or click → `GET /api/map/footprints?bbox=` (from `kb`)
   → GeoJSON. A question scoped to a drawn area runs flow 1 with the
   geometry attached; any vector layer in the answer returns as GeoJSON.
3. **Runs:** `GET /api/runs/` → backend queries Dagster GraphQL →
   normalized JSON → TanStack Table. `POST /api/runs/trigger/` (Admin
   only) → Dagster GraphQL `launchRun` mutation → returns the new run id.

## Invariants (the AI must never violate)

- The portal never writes to the `kb` database or any S3 bucket. Read-only
  credentials enforce this; code that needs write access is a design error.
- The agent's `sql_query` tool is SELECT-only. DDL/DML is rejected before
  execution, and DuckDB runs with no write credentials anyway.
- The client never composes queries or computes answers; it displays what
  the API returns.
- Every answer's citations reference asset UUIDs from the catalog — an
  uncited factual claim about the data is a bug.
- Secrets are referred to by name (`DATABASE_URL`), never by value, in
  logs, prompts, or diary entries. Chat content is internal data: it stays
  in `portal`, never in application logs.
- Never hardcode hex values or raw Tailwind color classes — design tokens
  only.
- Do not invent endpoints, tables, or tools beyond this document and the
  specs; if something needed is missing, stop and ask.
