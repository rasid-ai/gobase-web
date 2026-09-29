# ADR-006: The root route resolves on session, not on path

**Status:** Accepted · 2026-09-06

## Context

context/ui-rules.md assigns `/` twice: to the **Landing** page for an
unauthenticated visitor, and to the **Map** workspace inside the shell.
HLR-027 requires the landing page "at the root"; HLR-001 requires every
other route to redirect an unauthenticated visitor to sign-in. Both
statements are intended, and the app has to satisfy them together.

## Decision

The SPA builds a different route tree depending on session state, so `/`
means different things to different visitors.

```text
unauthenticated              authenticated
  /        Landing             /        Map (shell)
  /signin  Sign in             /runs    Runs (shell)
  *     -> /signin             *     -> /
```

Consequences that follow, and are not optional:

- The tree cannot be chosen until the boot refresh resolves. Until then
  the app renders a neutral boot state — rendering either tree early
  flashes the wrong page (HLR-002).
- The workspace has no URL of its own. A link to the workspace is a link
  to `/`, and is only meaningful to someone signed in.
- **Every exit path must name its destination explicitly.** Because the
  destination depends on the current URL rather than on the event, ending
  a session at `/` renders the anon `/` — the landing page — where
  HLR-004 demands the login screen. An expired session is therefore
  tracked separately from a deliberate sign-out (`sessionExpired` in the
  auth context) and redirects to `/signin`. This was a real bug, caught
  by the HLR-004 test, not a hypothetical.

## Rejected

**Landing at `/`, workspace at `/map`.** Gives the workspace a linkable,
bookmarkable URL and makes the sign-out destination unambiguous, since
each path means one thing to everyone. Rejected because it contradicts
ui-rules.md line 17 and would need a doc amendment, and because a
bookmarkable workspace URL has little value in an app where every route
is behind auth anyway. The trade is real: we accepted a sharper coupling
between session state and routing in exchange for leaving the UI rules
as written.

## Revisit when

The workspace needs deep-linkable state (a shared session, a specific
area or run), or a third role appears whose landing destination differs
again. Either would make path-per-screen the simpler model.
