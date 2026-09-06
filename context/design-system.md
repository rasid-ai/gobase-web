# Design System

Token values live in `frontend/src/styles/tokens.css` and only there;
this file explains what they mean. One fact, one home.

## Origin

The system merges two sources (docs/adr/005):
- **Structure** from the tweakcn "Witch Rave" theme: the light/dark tonal
  ladder, flat surfaces with **zero shadows** and hairline borders,
  radius 0.375rem, tracking −0.015em, Inter + JetBrains Mono.
- **Identity** from the Rasid brand: emerald `#12b085` =
  `oklch(0.6734 0.1347 167.3)` (sampled from rasid.ai) on green-cast
  darks (hue ≈ 174°). Every neutral was re-hued from the theme's indigo
  (277°) to Rasid's green family (≈ 168–174°).

## Color semantics

- **Primary** is the Rasid emerald. Dark mode uses the brand value
  exactly (it reads as it does on rasid.ai); light mode deepens it to
  L 0.60 so white-on-primary holds contrast. Ring, focus, active
  navigation, links, and success all key off this hue.
- **Secondary** is the deep pine chip color (Rasid's tag/badge green),
  filled with light text.
- **Destructive** is deepened in light mode (L 0.577) for contrast; in
  dark mode it pairs with a near-black foreground, like primary does.
- **Charts** rotate emerald → pine/blue → light emerald → amber → red;
  never rely on color alone to distinguish series.

## Geo Portal tokens

- `--map-result` (emerald) — answer vector layers. `--map-footprint`
  (blue) — asset footprints/coverage, deliberately *not* green so data
  extent never reads as an answer. `--map-selection` (amber) — the drawn
  question rectangle, distinct from both. Fill opacity is applied in the
  MapLibre style (~0.25 fills, solid strokes), reading these variables.
- `--status-success / -running / -failed / -queued` — run states on the
  Runs page. Badges tint the token to ~15% for background with the token
  itself as text.
- Basemaps pair with the theme: a light neutral style (Positron-class)
  and a dark neutral style (Dark Matter-class); the map style switches
  with the theme toggle.

## Typography & voice

- **Inter** carries everything; **JetBrains Mono, uppercase,
  letter-spaced** is the Rasid signature — reserved for *data chrome
  only*: coordinates, H3 ids, run ids, sensor/asset metadata, timestamps.
  Never for headings, buttons, or body text; overuse turns identity into
  noise.
- **One exception: the pre-auth pages.** The landing and sign-in screens
  use mono for their section micro-labels ("Geo Portal", "Ask", "See",
  "Monitor", "Sign in"). Those pages speak in a marketing voice, and
  rasid.ai uses mono micro-labels the same way (ADR-005). The
  data-chrome-only rule stands unchanged everywhere inside the shell.
- Surfaces are flat: hierarchy comes from borders and tone, never
  shadows.

## Rules

- Feature code uses semantic tokens only — never raw hex, never raw
  Tailwind color classes (CLAUDE.md non-negotiable).
- Every token has a light and a dark value; a component that only works
  in one theme is broken.
- The light theme has no Rasid reference (their site is dark-only) — it
  is this repo's interpretation and the first thing to show the firm for
  sign-off.
