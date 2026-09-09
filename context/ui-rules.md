# UI Rules

## Pages

Pre-auth, outside the shell:

- **Landing** (`/`, unauthenticated) — describes the tool (the three
  capabilities), with sign-in as the only action. No knowledge-base
  data and no API calls beyond auth. Renders in the visitor's system
  theme; the theme toggle exists only inside the shell.
- **Sign in** (`/signin`) — credentials form; success lands on the Map
  workspace.

Two routes inside the shell (persistent sidebar layout):

- **Map** (`/`) — the main workspace. The map fills the page; the chat is
  a docked, collapsible side panel on the same screen. The panel holds the
  session list and the active conversation. Vector layers from answers
  render on this map (toggleable per layer); clicking a point opens the
  covering-assets list grouped by data type; the rectangle tool scopes the
  next question to the drawn area.
- **Runs** (`/runs`) — run list, newest first, with a manual refresh
  control; selecting a run expands it in place to its per-step detail.
  Not a data grid: the pipeline runs weekly, so the list is one or two
  rows and a table's machinery would earn nothing. The trigger action
  renders only for Admin and always behind a Radix confirm dialog.

## Conventions

- **Answers show the answer and its citations — nothing else.** No tool
  trace, no query text, no internal step narration in the UI.
- Citations are interactive: selecting one shows the cited asset's
  metadata.
- Theme: light and dark, user toggle in the shell, remembered per browser.
  Both themes come entirely from design tokens; a component that only
  works in one theme is broken.
- Every data view has explicit loading, empty, and error states.
- Forms use React Hook Form + Zod inside Radix Dialogs; mutations go
  through TanStack Query and invalidate affected queries.
- The client renders API output only: no client-side spatial computation
  beyond display, no client-composed queries, no business logic.
- Design tokens only — never hardcoded hex or raw Tailwind color classes.
- Component inventory lives in context/ui-registry.md; design tokens live
  in context/design-system.md.
