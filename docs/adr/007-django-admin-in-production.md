# ADR-007: Django admin is served in production

**Status:** Accepted · 2026-09-06

## Context

Portal roles (Admin | Viewer) are a `UserProfile` row inlined into stock
Django admin — that is the whole of the role-assignment UI, and README
documents it as the way an operator grants access. There is no role
endpoint and no plan for one.

context/architecture.md routes only two paths on the host nginx: `/` to
the frontend container and `/api` to the backend container. Under that
routing, `/admin/` reaches the SPA, which knows nothing about it, so the
only administrative surface the portal has is unreachable the moment it
is deployed. Django's own static files are not served either: the image
runs no `collectstatic` and the project has no WhiteNoise, so admin would
render unstyled even once routed.

The deployment slice forced the question, because a deploy that cannot
onboard its first Viewer is not a deploy.

## Decision

Host nginx routes two further prefixes to the backend container:
`/admin/` and `/django-static/`. The backend image runs `collectstatic`
at build time and serves those files with **WhiteNoise** from inside the
container; nginx proxies rather than serving from a shared volume.
`STATIC_URL` becomes `/django-static/` so the prefix can never collide
with anything the SPA emits at `/assets/` or adds at the root later.

Both environments — the firm's VPS and the developer VPS — are routed
identically. Consequences that follow, and are not optional:

- Django's session and CSRF cookies now exist on the production origin
  alongside the JWT surface. They are unrelated to the refresh cookie,
  which stays scoped to `Path=/api/auth`, but both must be `Secure` in
  production: `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` are on
  wherever `DEBUG` is off.
- Admin is a password-only surface in front of the same accounts that
  hold JWT sessions, and it is reachable from the public internet. The
  Django superuser password is therefore a real production credential,
  not a local convenience.
- `/admin/` and `/django-static/` are part of the nginx vhost contract.
  A host set up without them has a portal that works and cannot be
  administered — the failure appears only when someone tries to add a
  user, which may be weeks later. infra/README.md carries the vhost.

Left open as operational hardening, not decided here: restricting
`/admin/` by source IP in the nginx vhost. It costs nothing to add per
host and does not change anything in this repo.

## Why

- Role assignment is the one administrative task this app has, and it is
  routine — a new analyst joining. Making it a developer task with an SSH
  session puts a person in the loop for something an operator should do.
- The alternative surfaces are not smaller in practice. A custom roles
  endpoint is a new authenticated write surface plus a UI to build; SSH
  access to the production host is a far broader privilege than admin.
- WhiteNoise over a shared static volume: the files ship inside the image
  that generated them, so a rollback to an old SHA gets that SHA's static
  files. A volume drifts from the running image and needs a compose
  mount on both hosts.

## Rejected

**No admin in production; roles via `manage.py` over SSH.** The smallest
public surface, and genuinely tempting for an internal tool. Rejected
because it trades a narrow, authenticated, auditable surface for handing
out shell access on the production host — the broader privilege of the
two — and because it contradicts the workflow README already documents.

**Admin on the developer VPS only.** Rejected because the environments
would then differ in routing, so the developer VPS stops being a
rehearsal of production, and production role changes still fall back to
SSH.

## Revisit when

The portal gains a real user-management screen of its own, or the firm
puts the VPS behind a VPN or identity proxy. The first removes the reason
to expose admin at all; the second makes the IP restriction moot and this
ADR's security argument obsolete.
