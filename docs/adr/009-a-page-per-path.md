# ADR-009: One path, one page — superseding ADR-006

**Status:** Accepted · 2026-09-15
**Supersedes:** docs/adr/006

## Context

ADR-006 built a different route tree per session state, so `/` was the
landing page for a visitor and the map workspace for a signed-in user.
It named its own trigger to revisit: *"the workspace needs
deep-linkable state (a shared session, a specific area or run)"*.

The Assets page is that trigger. Browsing the catalog and then asking
"where is this one?" only works if an asset can be named in a URL —
`/map?asset=<uuid>` — and a link to the workspace is worth nothing when
the workspace has no address of its own.

ADR-006 also recorded a real bug this shape caused: because the exit
destination depended on the current URL rather than on the event, ending
a session at `/` rendered the landing page where the login screen was
required. It was fixed by tracking an expired session separately. That
fix stands; the shape that made it necessary does not.

## Decision

Every path means one thing to everyone.

```text
unauthenticated              authenticated
  /        Landing             /        -> /map
  /signin  Sign in             /map     Atlas
  *     -> /signin             /assets  Assets
                               /runs    Data Governance
                               *     -> /map
```

The tree is still chosen by session state, because `/` has nothing to
show a signed-in user and the app must not render the shell to a
visitor. What changed is that no path *below* the root carries two
meanings.

Consequences that follow, and are not optional:

- **The workspace has an address.** `/map?asset=<uuid>` survives a
  reload and can be pasted to a colleague. The `asset` parameter *is*
  the selection rather than a copy of it, so clearing the selection must
  remove the parameter or the link re-selects on the next render.
- **The boot state stays.** The tree still cannot be chosen until the
  refresh resolves; rendering either one early flashes the wrong page.
  That part of ADR-006 is unchanged.
- **Sign-in names its destination**, `/map`, as does every other exit.
  This was already required by ADR-006 and is now simply easier to get
  right, because the destination no longer depends on where you were.
- **The active-navigation rule collapses to one line.** No path is a
  prefix of another, so every link owns its subtree and the root needs
  no special case.

## Why

- The asset deep link is the feature, and it cannot exist without this.
- The trade ADR-006 accepted — a sharper coupling between session state
  and routing, in exchange for leaving context/ui-rules.md as written —
  is no longer worth it with three pages instead of two. ui-rules.md is
  amended in the same change.

## Rejected

**Keep `/` as the workspace and deep-link as `/?asset=<uuid>`.** It
works, and it is the smallest change. Rejected because it keeps the one
thing ADR-006 flagged as the source of a real bug, while adding a third
page that would have to reason about it. The cost of the larger change
is one route file and its tests.

## Revisit when

A third role appears whose home is not the map, or the workspace needs
more of its state in the URL than one asset id — a drawn area, a chat
session — at which point the parameter set deserves designing rather
than growing.
