# ADR-030: A raster read may take five minutes

**Status:** Accepted · 2026-11-15
**Changes:** docs/adr/029, its bound for a slow lake (60 seconds)

## Context

ADR-029 bounded one raster read at 60 seconds (`RASTER_READ_TIMEOUT_SECONDS`)
and one lake request at 30 seconds (`GDAL_HTTP_TIMEOUT`). The Ask agent gave
up even sooner: it waited 15 seconds for any backend call. Ali, 2026-11-15:
the lake will not answer a raster in 15 seconds. A raster may be 3 GB.

A statistics read takes about 4 million pixels, from an overview (a stored
low-resolution copy) when there is one, so a large file alone does not make
it slow. What makes it slow is a raster with no overviews, or a slow link
between the portal and the lake. Either one can take minutes.

## Decision

Ali chose five minutes.

- `RASTER_READ_TIMEOUT_SECONDS` defaults to **300**.
- One lake request may take **120 seconds** (`GDAL_HTTP_TIMEOUT`). The
  largest request is about 8 MB, so this works on a link of 0.6 Mbit/s.
- The bounds for a dead lake don't change. Connect is 5 s, and a request
  that drops below 1 KB/s for 8 s is ended. A dead or stalled lake still
  answers 503 within 8 to 24 seconds.
- The agent waits **330 seconds** for `raster-stats` and 15 for everything
  else. Its turn limit is 8 minutes, and it sends a keep-alive line every 15
  seconds, so the gateway's 120-second read timeout
  (`AGENT_STREAM_TIMEOUT_SECONDS`) doesn't cut the stream (gobase-agent
  ADR-012).

## Consequences

- A slow raster question holds one backend thread for up to five minutes.
  Nothing limits how many such reads run at once (ADR-029). Several at once
  could use up a worker's threads.
- Keep `RASTER_READ_TIMEOUT_SECONDS` below the agent's
  `BACKEND_RASTER_TIMEOUT_SECONDS`. Otherwise the agent gives up first, and
  the backend keeps reading for no one.
- nginx already allows the Ask stream an hour (`proxy_read_timeout 1h`,
  infra/README.md).
