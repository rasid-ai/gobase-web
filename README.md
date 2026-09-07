# Geo Portal

Internal web app over the geospatial knowledge base. See `context/` for how
the system is built and `specs/` for what it must do.

## Local development with Docker

The fastest way in, and the closest to what ships: both services build from
the same Dockerfiles CI uses, so there is no second recipe to keep in sync.

```bash
docker compose -f docker-compose.dev.yml up --build
```

Backend on <http://localhost:8000>, frontend on <http://localhost:5173> with
HMR. Migrations run from the backend image's entrypoint exactly as they do in
production.

One prerequisite the host setup below does not need: **Postgres must accept
TCP connections with a password.** Containers reach the host database over the
Docker gateway, so a default install using peer auth over the unix socket will
be refused. Give the portal role a password, make sure `listen_addresses`
covers the Docker bridge, and allow `172.16.0.0/12` with `scram-sha-256` in
`pg_hba.conf` — the same shape as a VPS, spelled out in
[infra/README.md](infra/README.md).

## Local development on the host


Prerequisites: Python 3.12, Node 22 LTS (`nvm use`), pnpm, PostgreSQL 16
running natively.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

createdb portal                 # `kb` is read-only and untouched by this slice
cp .env.example .env            # then fill in PORTAL_DB_USER etc.
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver 8000
```

Roles are assigned in Django admin at <http://localhost:8000/admin/> —
each user gets a "Portal role" inline (Admin or Viewer). A user with no
profile row is treated as a Viewer.

On a local Postgres using peer auth, set the host to the socket directory
rather than `localhost`, which forces TCP and a password:

```
PORTAL_DB_HOST=/var/run/postgresql
```

### Frontend

```bash
cd frontend
nvm use            # Node 22, per .nvmrc
pnpm install
pnpm dev           # http://localhost:5173
```

`pnpm dev` proxies `/api` to `http://127.0.0.1:8000`, so development is
same-origin exactly like production behind nginx. The refresh cookie then
behaves identically in both, and CORS is never needed.

### The API contract

`backend/openapi.yaml` is the only backend↔frontend contract, and the
frontend client is generated from it — never hand-written. After changing
any endpoint or serializer:

```bash
cd backend && .venv/bin/python manage.py spectacular --file openapi.yaml
cd ../frontend && pnpm orval
```

### Deployment

`dev` deploys to the developer VPS, `main` to the firm's VPS, through one
pipeline: checks, then both images to GHCR, then `infra/deploy.sh` over SSH.
Per-host setup — nginx vhost, Postgres roles, the GHCR login and the five
GitHub Environment secrets — is in [infra/README.md](infra/README.md).

### Checks

```bash
cd backend  && .venv/bin/python -m pytest && .venv/bin/ruff check .
cd frontend && pnpm test && pnpm lint && pnpm build
```

Tests carrying a requirement's done criteria are tagged with its HLR id —
`@pytest.mark.hlr("HLR-002")` on the backend, the id in the `describe`
name on the frontend — so the traceability check can find them.

A test run warns `No directory at: backend/staticfiles/` until the first
`manage.py collectstatic`. WhiteNoise serves Django admin's assets in
production (docs/adr/007) and the middleware is deliberately not conditional
on `DEBUG`, so development runs the same stack production does.
