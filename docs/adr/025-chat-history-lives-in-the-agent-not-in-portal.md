# ADR-025: Chat history lives in the agent's sessions bucket, not in `portal`

**Status:** Accepted · 2026-11-08

## Context

context/architecture.md puts chat sessions, messages and citations in
`portal`, the database this portal owns (docs/adr/002), and CLAUDE.md says
chat content stays there. Two plans followed:

- **The 3 Nov plan:** Agno would own sessions in a third Postgres database,
  `agent`.
- **A first proposal on 2026-11-08:** keep the agent stateless and store
  history in `portal`, with the backend resending it each turn.

Ali chose that the agent's framework, Strands, owns the sessions, "this is
what it's built for". He also chose S3 in local development and production
alike, on the MinIO that already serves this portal's and the data
platform's buckets.

## Decision

- **The agent stores every session** in a bucket of its own on the existing
  MinIO, under one prefix per user: `users/<user_id>/session_<id>/`.
  Reading, writing and deleting always use the user id this backend sends,
  so one user cannot reach another's sessions.
- **Each answer's references are saved with it** (cited assets, map layers,
  passages, raster results), so reopening a session brings them back.
- **`portal` stores nothing about chat.** No sessions, messages, citations
  or layers. The chat app lists, reads and deletes a user's sessions
  through the agent's API, as that user.
- **This backend still owns who the user is.** The agent trusts the user id
  because only this backend holds `AGENT_SERVICE_TOKEN` (docs/adr/023).

## Rejected

- **History in `portal`**, with a stateless agent. It needs no extra store,
  but Ali chose Strands' own session handling.
- **A third database on the instance**, as the 3 Nov plan had with Agno.
  Strands has no Postgres store, so it would mean writing one and owning its
  migrations. docs/adr/002 stays as it is: two databases, one instance.

## Consequences

- **Some text changes when the chat app is built:**
  - the `portal` row of context/architecture.md's database table;
  - the "Ask" data flow there;
  - CLAUDE.md's "chat content stays in `portal`", which becomes "in the
    agent's sessions bucket".
  - specs/ask.md's "citations persist in portal".
- **Chat history is backed up with the MinIO bucket,** not with Postgres.
- **Deleting a user's chat is deleting their prefix** in the agent's
  bucket. Deleting the Django user does not remove it on its own.
- **A layer drawn from an answer is fetched from `/data`** with the asset,
  area and filter the reference carries (docs/adr/024). No GeoJSON is
  stored anywhere for it.

## Revisit when

- Search across a user's history, or listing at thousands of sessions per
  user, is asked for. The agent's bucket listing would then need an index.
