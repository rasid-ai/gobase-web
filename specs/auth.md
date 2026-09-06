# Spec: Authentication & Roles

Requirement IDs are global across all specs, never reused or renumbered.
Roles: **Admin**, **Viewer**. Implementation mechanics: context/architecture.md.

---

**HLR-001** — The system SHALL require an authenticated user for every
API endpoint except login, and for every page except the landing and
sign-in pages.
Priority: Must · Phase: MVP
**Done means:**
GIVEN no valid session
WHEN any `/api/` endpoint except `/api/auth/login` is called
THEN the response is 401 and contains no data
AND GIVEN an unauthenticated visit to any SPA route other than the
landing page
THEN the user is redirected to the sign-in screen

---

**HLR-002** — WHEN a user submits valid credentials, the system SHALL
start a session that survives a page refresh without re-entering
credentials.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a user logged in
WHEN the browser page is reloaded
THEN the user remains signed in and no credential prompt appears

---

**HLR-003** — WHILE a session is active, the system SHALL renew it
transparently; the user never sees an interruption while their refresh
credential remains valid.
Priority: Must · Phase: MVP
**Done means:**
GIVEN an expired access token and a valid refresh credential
WHEN the user performs any action
THEN the action completes successfully with no visible error

---

**HLR-004** — IF the session can no longer be renewed, THEN the system
SHALL end it and return the user to the login screen.
Priority: Must · Phase: MVP
**Done means:**
GIVEN an expired or revoked refresh credential
WHEN the user performs any action
THEN they are returned to the login screen and no partial data renders

---

**HLR-005** — The system SHALL expose the signed-in user's identity and
role to the client, and the client SHALL gate navigation from it.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a signed-in Viewer
WHEN the SPA loads
THEN `GET /api/auth/me` returns `{username, role: "viewer"}`
AND Admin-only controls are not rendered

---

**HLR-006** — WHILE the caller's role is Viewer, the system SHALL reject
Admin-only actions server-side, regardless of what the client renders.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a Viewer's valid session
WHEN `POST /api/runs/trigger/` is called directly
THEN the response is 403 and no pipeline run is launched

---

**HLR-007** — WHEN a signed-in user submits their current password and a
new password, the system SHALL change the password; IF the current
password is wrong, THEN the system SHALL reject the change.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a signed-in user
WHEN they submit a wrong current password
THEN the response is an error and the password is unchanged
AND WHEN they submit the correct current password
THEN the next login succeeds only with the new password

---

**HLR-008** — IF a signed-in user has no role assigned, THEN the system
SHALL treat them as Viewer.
Priority: Must · Phase: MVP
**Done means:**
GIVEN a user with no profile row
WHEN `GET /api/auth/me` is called
THEN the role returned is "viewer"
AND WHEN they call an Admin-only action
THEN the response is 403

---

**HLR-027** — The system SHALL show unauthenticated visitors a landing
page at the root that describes the tool and offers sign-in as its only
action; it SHALL expose no knowledge-base data.
Priority: Must · Phase: MVP
**Done means:**
GIVEN an unauthenticated visitor
WHEN they open the root URL
THEN the landing page renders with a sign-in entry
AND no data from the knowledge base appears anywhere on it
AND WHEN they open any other route
THEN they are redirected to the sign-in screen
