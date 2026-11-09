# The Ask agent — `gobase-agent`

The engine behind Ask: one Strands agent with nine read-only tools, run as a
separate service in its own repo and deployed alone (docs/adr/023). It runs
the model and the tools; this backend runs none of that. This backend is its
only caller, and `apps/chat/agent.py` is the only module that speaks to it.

The agent's own design is in the `gobase-agent` repo
(`context/architecture.md`, `docs/adr/001`–`005`). This file is the contract
from the portal's side: what the gateway sends, and what it accepts back.
Where the agent's design left a field name open, this file fixes it, and the
agent is built to match.

Built on 2026-11-09 against a stub agent. The real agent is not built yet.

## Settings

| Setting | What it is |
|---|---|
| `AGENT_URL` | The agent's base URL, scheme included. Blank is a supported state: every chat endpoint answers 503 before any call, and the panel says "Ask is unavailable." |
| `AGENT_SERVICE_TOKEN` | What the agent requires from its one caller. Sent as `Authorization: Bearer <token>`. The agent compares it in constant time. Blank sends no `Authorization` header at all: `Bearer ` with nothing after it is an illegal header value that httpx refuses to send, which made every call look like an unreachable agent (503). An agent that wants a token then answers 401, which shows as a 502. |
| `AGENT_TIMEOUT_SECONDS` | Connecting, and the whole of a short call (list, read, delete). Default 10. |
| `AGENT_STREAM_TIMEOUT_SECONDS` | The longest silence allowed between two pieces of a streamed answer. Not a cap on the whole answer: the agent bounds that itself. Default 120. |

## Who the user is

Every call names the signed-in user by their Django primary key
(`str(user.pk)`), in the path. The agent keeps that user's sessions under
`users/<user_id>/` in its own bucket (docs/adr/025), so the id is the privacy
boundary: the backend always sends the caller's own id, and never one from
the request. The agent trusts it because only this backend holds the token.

Session ids are UUIDs. The SPA mints a new one for a new chat; the backend's
URL routes accept only a UUID, so nothing else reaches the agent's S3 keys.

## How the agent calls back

The agent's tools read the knowledge base through this backend's API
(docs/adr/024), the other way round from everything above. For that it holds
an API key (docs/adr/021) of its own Viewer user, `gobase-agent`, which has
no usable password. It sends `Authorization: Api-Key <key>`, read from
`BACKEND_SERVICE_TOKEN` in the agent's environment. A key can only read, so
the agent can never write, and it sees what any Viewer sees. Issue it with
`manage.py create_api_key gobase-agent "<where it runs>"`; revoke it in
Django admin.

The two secrets are different and go opposite ways: `AGENT_SERVICE_TOKEN`
is what this backend shows the agent, and the API key is what the agent
shows this backend.

## The calls

| Portal endpoint (SPA → backend) | Agent call (backend → agent) |
|---|---|
| `GET /api/chat/sessions` | `GET /v1/users/{user_id}/sessions` |
| `GET /api/chat/sessions/{id}` | `GET /v1/users/{user_id}/sessions/{id}` |
| `DELETE /api/chat/sessions/{id}` | `DELETE /v1/users/{user_id}/sessions/{id}` |
| `POST /api/chat/sessions/{id}/turns` | `POST /v1/users/{user_id}/sessions/{id}/turns` |

`backend/openapi.yaml` has the portal's shapes. The agent's are the same JSON,
except where noted below.

### Sessions

The agent answers the list as `{"results": [session, …]}`, newest first. A
session is `{session_id, title, created_at, updated_at}`; `title` is the
session's first question. Reading one adds `turns`, oldest first, each
`{prompt, text, references, incomplete}`. `incomplete` may be left out and
then means false. `404` means the user has no such session.

### One turn

The backend sends `{"prompt": "…", "context": {…}}` with
`Accept: text/event-stream`. `context` holds only the fields the map had:

- `viewport` — `[min_lon, min_lat, max_lon, max_lat]`, what the map shows;
- `point` — `[lon, lat]`, a clicked point;
- `area` — a drawn polygon as WKT, already checked by the catalog's
  `AreaField` (one ring, closed, never crossing itself);
- `asset_id` — the asset selected in the map's panel.

An unknown session id starts a new session. The agent answers `200` with a
stream of server-sent events: a name on an `event:` line, and JSON on a
`data:` line.

| Event | Agent's `data` | What the SPA receives |
|---|---|---|
| `step` | `{tool, status, note?}` — `status` is `started`, `finished` or `failed` | the same, with `event` |
| `text` | `{delta}` | the same, with `event` |
| `reference` | one reference (below) | `{event, reference}` |
| `done` | `{text, references}` — the whole answer, checked | the same, with `event` |
| `error` | `{message, incomplete}` | the same, with `event` |

The backend writes each event to the SPA with the whole event, `event`
included, as one JSON line on `data:` (`apps/chat/sse.py`).

### References

One flat shape, `ChatReference`. `kind` says which fields are set:

| `kind` | Fields |
|---|---|
| `asset` | `asset_id` |
| `layer` | `asset_id`, `area` (WKT) or `bbox`, `filter`, `total` |
| `passage` | `asset_id`, `chunk_id`, `page` (from 1) |
| `raster` | `asset_id`, `area` or `bbox`, `stats` |
| `frame` | `bbox` |

`filter` is `{column, op, value}`, with `op` one of `equals`, `contains`,
`in`, `<`, `>` (docs/adr/024). `stats` is an open object: the figures the
answer used, per band or per class. The backend passes a reference on with
only its kind's fields; it does not look the asset up.

## What the backend checks

The relay is a gateway, not a pass-through. It reads the agent's stream event
by event and passes on only what fits the contract:

- **A known event that does not fit its shape** (bad JSON, a missing field, a
  reference with no `asset_id`) ends the answer. The SPA gets a last
  `error` event with `incomplete: true`, and never the bad event.
- **An unknown event name** is skipped, so a newer agent can add one without
  breaking an older portal.
- **Fields the contract does not name** are dropped.
- **A stream that ends with no `done` or `error`**, breaks, or stays silent
  past `AGENT_STREAM_TIMEOUT_SECONDS` ends with an `error` event of the
  backend's own: "The answer was cut off."
- **The browser leaving** (Stop, closing the tab) cancels the relay, and the
  backend closes the agent's stream with it.

Session list and read answers go through the same serializers; one that does
not fit is a 502.

## Failures

| What happened | Status to the SPA |
|---|---|
| `AGENT_URL` blank | 503, before any call |
| The agent is unreachable or times out on connect | 503 |
| The agent answers 502, 503 or 504 (not ready, or a proxy in front of it) | 503 |
| The agent answers any other error | 502 |
| The agent answers 404 for a session | 404 |
| The answer fails after it started streaming | 200, ending in an `error` event |

The 502 carries no upstream text: the agent's errors describe our token and
our configuration, not anything the user can act on. They go to the log as a
status only.

## Runtime notes

- **The relay is an async Django view** (`relay_turn`), because the agent's
  tool calls come back into this same backend while it relays. Checked live
  with a stub agent: one uvicorn worker served three streaming answers and a
  short call at once, the short call in under 50 ms. DRF's views are
  synchronous, so `relay_turn` authenticates with the project's
  `DEFAULT_AUTHENTICATION_CLASSES` inside `sync_to_async` (so an API key gets
  the same 403 as on any other write, docs/adr/021), and names a schema-only
  `TurnView` as its `cls` so drf-spectacular puts it in `openapi.yaml`.
- **ASGI is required to stream.** `runserver` is WSGI and would hold the
  answer back until it finished; `docker-compose.dev.yml` runs uvicorn with
  `--reload` for that reason. Prod already runs uvicorn workers.
- **nginx must not buffer.** The response sets `X-Accel-Buffering: no`, and
  the `/api` location in infra/README.md already has `proxy_buffering off`
  and `proxy_read_timeout 1h`.
- **Nothing about chat is logged**: not the question, not the answer, not
  the agent's error text. Only exception types, statuses, and the names of
  fields that failed a check.
- **Networking between the backend and the agent is not decided** (TLS,
  firewall or VPN; docs/adr/023). The token travels in clear over plain
  http until it is.

## Testing

`apps/chat/tests` fake the agent at its transport: `agent.TRANSPORT` takes an
`httpx.MockTransport`, which serves the sync client and the async one. The
turn tests go through Django's `AsyncClient` and read the whole stream.
