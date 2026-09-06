# ADR-005: Design tokens — Witch Rave structure, Rasid brand

**Status:** Accepted · 2026-09-05

## Context

The interim rule (shadcn defaults, tokens only) needed replacing with a
real system. Available inputs: the tweakcn community theme "Witch Rave"
(complete, coherent shadcn token set, flat corporate aesthetic) and the
Rasid brand (emerald #12b085 on green-cast near-black, mono micro-labels
— sampled from rasid.ai screenshots; dark-only, no token structure).

## Decision

Merge them in code: keep Witch Rave's full token architecture, tonal
ladder, flat zero-shadow surfaces, radius, and type stack; re-hue every
neutral from indigo (277°) to Rasid's green family (≈174°); set primary
to the Rasid emerald — exact in dark mode, deepened to L 0.60 in light
mode for contrast; deepen light-mode destructive for the same reason.
Add Geo Portal tokens (map-result/footprint/selection, run statuses).
Source of truth is `frontend/src/styles/tokens.css`; documentation is
`context/design-system.md`.

## Rejected

- **Witch Rave unmodified** — its neutrals are indigo; the app would not
  read as Rasid's.
- **Figma designer loop** — right only when a designer owns the theme;
  today it adds a round-trip with no owner. Trigger to revisit below.
- **From-scratch palette** — discards a proven, contrast-balanced ladder
  for no gain.

## Revisit when

A designer joins with a Figma-first workflow, or the firm rejects the
light theme (which has no Rasid reference to copy — it is our
interpretation and needs their sign-off).
