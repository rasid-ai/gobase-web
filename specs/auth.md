# Authentication & Roles

Two roles: **Admin** and **Viewer**. Implementation mechanics live in
context/architecture.md; the route-tree decision is docs/adr/006.

Built.

## Access

Every API endpoint except login requires an authenticated user, and every
SPA page except the landing and sign-in pages does too. An unauthenticated
call gets a 401 carrying no data; an unauthenticated visit to any other
route redirects to sign-in.

Unauthenticated visitors get a landing page at the root. It describes the
tool, offers sign-in as its only action, and shows no knowledge-base data.

## Sessions

Valid credentials start a session that survives a page refresh without
re-entering them. While the refresh credential holds, the session renews
transparently — the user never sees the interruption. Once it can no
longer be renewed the session ends and the user returns to sign-in,
without partial data rendering on the way out.

## Roles

`GET /api/auth/me` returns the signed-in user's username and role, and the
client gates navigation from it. Admin-only actions are rejected
server-side regardless of what the client chose to render, so calling one
directly as a Viewer gets a 403. A user with no role assigned is treated
as a Viewer.

## Passwords

A signed-in user can change their password by submitting the current one
alongside the new. A wrong current password is rejected and leaves the
password unchanged.
