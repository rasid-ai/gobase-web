# UI Registry

Which components exist and what they match. One component, one line —
history belongs in the diary, reasoning in an ADR (guarded by /imprint).

| Component | Matches |
|---|---|
| `ui/Button` | Flat, hairline, zero shadow, radius `--radius`. Variants: primary (emerald fill, near-black text), outline, ghost, link. Sizes sm/md/lg. `asChild` for link buttons. |
| `ui/Input` | h-10, `bg-input`, hairline border, `--ring` focus ring; `aria-invalid` turns the border and ring destructive. |
| `ui/Label` | Radix label, 14px medium, paired with an `Input` by `htmlFor`. |
| `ui/Alert` | Inline form-level error. Destructive hairline border on a 10% destructive tint. No icon, no shadow. |
| `PortalWordmark` | GEO + emerald PORTAL, 14px bold, tracking 0.1em. The header identity mark on every page. |
| `LandingPage` | Unauthenticated root. Header, hero + decorative map graphic, three capability cards, footer. Mono micro-labels. No API calls. |
| `SignInPage` | Centered 380px column, mono eyebrow, hairline card, RHF + Zod, inline `Alert` on failure. |
| `AppShell` | Authenticated frame: header, Map/Runs nav, mono identity chip, theme toggle, sign out. Runs owns its whole subtree for the active highlight. |
| `ui/Badge` | Status pill: token tinted 15% behind the token as text, radius-full. A dot precedes the label — disc for live states, ring for inert ones, so colour never carries the meaning alone. Tones: success/running/failed/queued/neutral. |
| `ui/Dialog` | Radix dialog. Hairline border on `bg-popover`, no shadow, overlay is `bg-background/80` with a 2px blur. Title, description, right-aligned footer. |
| `ui/Skeleton` | Pulsing `bg-muted-foreground/10` block for a data view that has not answered. |
| `RunsPage` | Runs list: page header with relative last-read, Refresh, and Admin-only Run pipeline. Rows in a hairline panel share one grid so run and step badges align; a row expands in place. Explicit empty, loading, and pipeline-unreachable states. |
