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
| `AppShell` | Placeholder authenticated frame: header, Map/Runs nav, mono identity chip, sign out. The real sidebar arrives with the workspace slice. |
