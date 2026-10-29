# ADR-021: Desktop clients sign in with an API key

**Status:** Accepted · 2026-10-26

## Context

A second client is coming: an ArcGIS Pro add-in. ArcGIS Pro is Esri's
desktop GIS; the add-in is a plugin for it, written in C#, in the repo
`Gobase-plugin`. Version one lists the catalog and loads vector layers into
the map. It does this through endpoints the SPA already uses:
`/api/catalog/assets`, `/api/map/assets/{asset_id}`,
`/api/map/assets/{asset_id}/data` and `/api/catalog/assets/{asset_id}/pdf`.

The only thing in the way is sign-in, which is built for a browser.
`POST /api/auth/login` returns an access token that lasts 15 minutes. The
refresh token lives only in an HttpOnly cookie on `/api/auth`. That cookie
changes on every use and is `Secure` in production (`config/settings.py`). A
desktop program can keep cookies, but then it has to store the user's
password or ask for it every seven days. Two refreshes sent at the same time
also sign it out.

context/project-overview.md listed "public or client-external access" as
out of scope.

## Decision

**Internal users may reach the API from a desktop client.** The public may
not. project-overview.md now says so.

**API keys, each tied to a user.**
- **Model:** `ApiKey` in `apps/accounts`, stored in `portal` (migration
  `0002_apikey`). Its fields are the user, a name, a prefix, a SHA-256 hash,
  the creation time, the last-used time and the revocation time.
- **Issuing:** an Admin issues keys in Django admin (docs/adr/007). Pick the
  user and name the key; the next page shows the key once. It is written into
  that page only, not into a message, because a message would travel in a
  cookie. `manage.py create_api_key <username> <name>` does the same from a
  shell. Only the hash is stored.
- **Revoking:** revocation is an admin action. A revoked key gets a 401. So
  does a key whose user has been disabled.
- **Format:** a key looks like `gbk_<prefix>_<secret>`. The 12 hex
  characters of the prefix find the row, and the secret is 256 random bits.
  A random secret that long needs no slow hash. It contains no `:`, so it can
  later be used as a Basic-auth password.

**Sent as `Authorization: Api-Key <key>`.**
- `ApiKeyAuthentication` comes after `JWTAuthentication` in
  `DEFAULT_AUTHENTICATION_CLASSES`.
- It sets `request.user` to the key's owner, and roles resolve as before.
- It uses its own header word, not `Bearer`. simplejwt rejects any `Bearer`
  value it cannot read, and DRF stops at the first rejection.

**A key can read, not act.** A request signed with a key gets a 403 for any
method other than GET, HEAD and OPTIONS. The authentication class checks
this, not a permission class. A view that sets its own `permission_classes`,
such as the Admin-only run trigger, would skip a default permission class.

**`last_used_at` is written at most once every five minutes.** It tells an
Admin whether a key is still in use. Writing it on every read would turn
every read into a write.

**openapi.yaml** describes the scheme as `apiKeyAuth`
(`apps/accounts/schema.py`), on every endpoint that requires sign-in.

## Why

- **A key instead of the browser session, for a desktop program.** It is one
  secret, kept in the Windows Credential Manager, and each key can be revoked
  on its own. No password is stored and there is no refresh race.
- **Read-only,** because a key sits on a laptop for months. A stolen key must
  not launch pipeline runs or change a password, even if its owner is an
  Admin.
- **Tied to a user,** so roles, `GET /api/auth/me` and every permission check
  keep working unchanged.

## Consequences

- **openapi.yaml has two consumers.** A change to an endpoint the add-in uses
  now breaks a client that ships separately. Those endpoints are the four
  above and `/api/auth/me`.
- **Nothing throttles a key.** `ScopedRateThrottle` is the fix when it
  matters (docs/adr/011).
- **The SPA is unchanged.** It never sees a key, and
  `frontend/src/api/generated` regenerates identical.
- **Rasters are not covered.** Giving a desktop client temporary credentials
  for the lake would bend the CLAUDE.md rule that anything carrying a
  credential goes through the backend. That is decided in its own ADR, once
  ArcGIS Pro has been tested against RustFS.

## Rejected

- **JWT and stored cookies, from the desktop.** It works, but it needs a
  stored password or a login every seven days, plus a refresh that never runs
  twice at once, written in C#.
- **simplejwt's body-based token views** (`TokenObtainPairView`,
  `TokenRefreshView`). They have the same 15-minute and seven-day lifetimes.
  They would also put a refresh token where the SPA's design keeps it out of
  reach of scripts.
- **`djangorestframework-api-key`.** Its keys are not tied to a user, so
  `request.user` stays anonymous. That means no role and no audit trail.
- **A permission class for the read-only rule.** See Decision.
- **Expiry dates on keys.** Not now. Revocation covers a lost laptop, and the
  last-used time shows keys nobody uses. Add `expires_at` if a policy asks for
  rotation.

## Revisit when

- The add-in gains chat, which needs POST with a key.
- OGC API Features is added, which needs the key as a Basic-auth password.
- People outside the team need keys, which needs self-service issuing and
  rate limits.
