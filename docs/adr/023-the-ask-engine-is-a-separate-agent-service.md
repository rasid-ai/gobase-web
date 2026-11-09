# ADR-023: The Ask engine is a separate agent service, and the backend is its only caller

**Status:** Accepted · 2026-11-08

## Context

context/architecture.md left the Ask engine — "LLM provider and
agent/orchestration design" — undecided, to get its own ADR before the chat
app is built. This is that ADR.

Two documents described the engine:

- **The 3 Nov plan** (an architect session with Ali, kept as `docs/PLAN.md`
  in the `gobase-agent` repo): an Agno service in its own repo, with this
  backend as the gateway.
- **Hasan Nasrallah's requirements v0.4** (4 Nov): built with Strands, one
  agent with a simple loop and nine named tools, "living in the portal
  backend", with an online and an offline mode.

Ali's ruling on 2026-11-08: Hasan's document is the requirement, not a
technical design to follow to the letter. Strands and the nine tools are
taken from it. Ali also set a rule for every service in this project: each
one is deployed alone.

The agent's own design is recorded in the `gobase-agent` repo
(`docs/adr/001`–`005`, `context/`).

## Decision

- **The engine is `gobase-agent`**, a separate service in its own repo: one
  Strands agent with Hasan's nine tools, behind a small HTTP API.
- **It is deployed alone**: its own image and compose file, on no Docker
  network shared with this portal. The backend reaches it at `AGENT_URL`.
- **This backend is its only caller.** The browser and the ArcGIS add-in
  talk to the backend as they do today, and never reach the agent
  (docs/adr/011 holds). The backend presents `AGENT_SERVICE_TOKEN` and
  passes the signed-in user's id with every call.
- **`apps/chat` is a gateway, not an engine.** It forwards the question and
  the map's context (viewport, clicked point, drawn area, selected asset) to
  the agent, and relays the agent's stream to the SPA as SSE. It runs no
  agent loop and calls no model. The relay is an **async view**: a sync view
  would hold a worker thread for the whole answer, while the agent's tool
  calls come back into this same backend and need workers of their own
  (docs/adr/024).

## Rejected

- **The engine inside this backend** (Hasan's v0.4). It would put model
  clients, an offline GPU mode, and the agent's release cycle into the
  Django image, and a long agent loop into Django's workers.
- **Agno** (the 3 Nov plan). Hasan's requirement names Strands.
- **A container on this portal's compose network** (the 3 Nov plan). Ali's
  rule: every service is deployed alone.
- **The browser calling the agent directly.** That would be a second public
  API carrying chat, and it breaks docs/adr/011.

## Consequences

- "The backend owns all LLM calls" (context/architecture.md, CLAUDE.md) is
  no longer true. The backend owns the gateway; the agent owns the model
  calls. Those files are updated when the chat app is built.
- The engine is no longer "undecided" in context/architecture.md and
  specs/ask.md.
- The backend and the agent talk across a real network. TLS, firewall or
  VPN are deferred, and decided before the chat app ships.
- New settings by name: `AGENT_URL`, `AGENT_SERVICE_TOKEN`. A blank
  `AGENT_URL` is a supported state: the chat panel says Ask is unavailable,
  and the backend answers 503 before any call, as with `GODOC_URL`.

## Revisit when

- The networking between the backend and the agent is decided.
