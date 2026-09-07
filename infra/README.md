# Host setup

One-time, manual, per VPS. Nothing here is automated: CI assumes a host that
already looks like this, and only copies `docker-compose.prod.yml` and
`deploy.sh` in before running the script.

Two hosts follow this document identically — the firm's VPS (deployed from
`main`) and the developer VPS (deployed from `dev`). They differ only in
domain, credentials, and the GitHub Environment that holds their secrets.

## 1. Deploy user and directory

```bash
sudo adduser --disabled-password deploy
sudo usermod -aG docker deploy          # so deploy.sh can drive compose

# Created as root, then handed over: /srv is root-owned, so `deploy` cannot
# make a directory there itself. CI writes into this path over scp, so the
# deploy user must own it, not merely be able to read it.
sudo mkdir -p /srv/geo-portal
sudo chown deploy:deploy /srv/geo-portal
ls -ld /srv/geo-portal                  # expect: drwxr-xr-x deploy deploy
```

`/srv/geo-portal` is the deploy path. It holds three files: the two CI copies
in, plus a `.env` that is **host-owned and never touched by CI**.

Add the public half of the CI SSH key to `/home/deploy/.ssh/authorized_keys`;
the private half goes into the environment's `VPS_SSH_KEY` secret.

## 2. GHCR login

The images are private, so each host authenticates once with a PAT scoped to
`read:packages` only:

```bash
sudo -u deploy sh -c 'echo "$GHCR_PAT" | docker login ghcr.io -u <github-user> --password-stdin'
```

`GHCR_PAT` is referred to by name; the value is pasted at the prompt and lives
only in the deploy user's `~/.docker/config.json`. It is not a repo secret —
CI pushes with the built-in `GITHUB_TOKEN` and never needs it.

## 2b. A host that runs other projects

Nothing here assumes an empty machine, but three things collide if they are
not checked:

- **Ports.** `BACKEND_PORT` and `FRONTEND_PORT` default to 8000 and 8080,
  which are the two most commonly taken ports on a shared box. Both bind to
  127.0.0.1, so a clash is a startup failure, not a security problem. Pick
  free ones and set them in `.env`:

  ```bash
  ss -ltnp | awk '{print $4}' | grep -oE '[0-9]+$' | sort -un | tr '\n' ' '
  ```

- **nginx.** Give the vhost an exact `server_name` — the IP or hostname this
  portal answers on. nginx matches `server_name` before falling back to a
  default server, so an exact match cannot steal another site's traffic, and
  it does not need `default_server` (claiming that would clash with whichever
  site already has it).

- **Images and containers.** The compose project name is pinned to
  `geo-portal` rather than inherited from the directory, and `deploy.sh` runs
  no host-wide `docker image prune` — that would delete other projects'
  dangling images.

## 3. PostgreSQL (native, not containerized)

Postgres 16 runs on the host. Containers reach it over the Docker gateway, so
it must accept TCP connections from the bridge network — a default install
listening only on the unix socket will not work.

The role owns the database rather than merely holding privileges on it. Since
Postgres 15 the `public` schema no longer grants CREATE to everyone, so a role
with `GRANT ALL PRIVILEGES ON DATABASE` can connect and still fail the first
migration with `permission denied for schema public`. The `public` schema is
owned by `pg_database_owner`, so making the role the database owner is what
actually lets Django create tables.

```sql
CREATE ROLE portal_app LOGIN PASSWORD '...';      -- PORTAL_DB_USER / PORTAL_DB_PASSWORD
CREATE DATABASE portal OWNER portal_app;

-- `kb` is owned by the data platform repo. This role only reads it
-- (docs/adr/002); it must never hold a write grant.
CREATE USER portal_kb_reader WITH PASSWORD '...';  -- KB_DB_USER / KB_DB_PASSWORD
GRANT CONNECT ON DATABASE kb TO portal_kb_reader;
\c kb
GRANT USAGE ON SCHEMA public TO portal_kb_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO portal_kb_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT TO portal_kb_reader;
```

In `postgresql.conf`, `listen_addresses` must include the Docker bridge
address (`172.17.0.1`, or `*` if the host firewall already blocks 5432 from
outside). In `pg_hba.conf`, allow the bridge subnet with `scram-sha-256`:

```
host    portal    portal_app          172.16.0.0/12    scram-sha-256
host    kb        portal_kb_reader    172.16.0.0/12    scram-sha-256
```

## 4. The `.env`

Copy `.env.example` from this directory to `/srv/geo-portal/.env` and fill it
in. `DJANGO_SECRET_KEY` must be unique per host and generated on the host —
never reused from development, never committed anywhere.

## 5. nginx vhost

nginx runs on the host, terminates TLS, and routes **four** prefixes. The
first two are the app; the second two exist because Django admin is served in
production (docs/adr/007) — a vhost without them gives a portal that works and
cannot be administered, and the gap only shows up the first time someone tries
to add a user.

```nginx
server {
    listen 443 ssl http2;
    server_name portal.example;

    ssl_certificate     /etc/letsencrypt/live/portal.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portal.example/privkey.pem;

    # Same-origin by construction: the SPA and the API share this server_name,
    # which is why the refresh cookie works and CORS is never configured.
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
        # Django must know the request arrived over TLS, or Secure cookies
        # never stick (SECURE_PROXY_SSL_HEADER in config/settings.py).
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE for streamed answers, from the Ask slice onward: buffering here
        # would hold a stream until it completed, which defeats the point.
        proxy_buffering off;
        proxy_read_timeout 1h;
    }

    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Optional hardening, left to the operator (docs/adr/007): restrict
        # admin to the office range. Costs nothing and changes nothing in the
        # repo.
        # allow 203.0.113.0/24;
        # deny all;
    }

    location /django-static/ {
        proxy_pass http://127.0.0.1:8000;
        include /etc/nginx/proxy_params;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        include /etc/nginx/proxy_params;
    }
}
```

Port 80 redirects to 443. Certificates via certbot.

## 6. GitHub Environment secrets

Each host has a GitHub Environment — `production` for the firm's VPS,
`development` for the developer VPS — holding five secrets. `deploy.yml`
picks the environment from the branch, so the same workflow reaches a
different host with no conditional beyond that.

| Secret | Value |
|---|---|
| `VPS_HOST` | Hostname or IP of this environment's server. |
| `VPS_USER` | The deploy user (`deploy`). |
| `VPS_SSH_KEY` | Private half of the CI key, in full including its header and footer lines. |
| `VPS_SSH_KNOWN_HOSTS` | Output of `ssh-keyscan -H <host>`, pasted verbatim. |
| `DEPLOY_PATH` | Absolute deploy path (`/srv/geo-portal`). |

`VPS_SSH_KNOWN_HOSTS` is pinned rather than discovered per run: a workflow
that trusts whatever answers on the first connection hands a deploy — and the
key it authenticates with — to anyone able to get in the middle of it.
Regenerate it if the host is ever rebuilt, or every deploy fails at the SSH
step.

Nothing else belongs in CI. `GHCR_PAT` is a host credential (step 2), and the
push to GHCR uses the workflow's built-in `GITHUB_TOKEN`.

## 7. First deploy

Push to the branch for this host and watch the Actions run. The workflow
copies `docker-compose.prod.yml` and `deploy.sh` into the deploy path, then
runs the script with `IMAGE_TAG` set to the commit SHA. The backend container
applies `portal` migrations from its own entrypoint on start.

Create the first superuser once the containers are up:

```bash
cd /srv/geo-portal
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Then sign in at `https://portal.example/admin/` and give each user a Portal
role. A user with no profile row is treated as a Viewer.

## Rolling back

Images for every deployed SHA stay in GHCR, each carrying its own migrations
and its own admin static files:

```bash
cd /srv/geo-portal
IMAGE_TAG=<old-sha> ./deploy.sh
```

A rollback across a schema change is not automatic — Django does not reverse
migrations on its own, and the older image will not know about a newer table.
