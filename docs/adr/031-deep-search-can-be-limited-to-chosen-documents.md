# ADR-031: Deep search can be limited to chosen documents

**Status:** Accepted · 2026-11-15
**Builds on:** docs/adr/020 (deep search), docs/adr/024 (the agent reads the KB through this API)

## Context

The Ask agent's `doc_passages` tool searches inside documents' text through
`GET /api/catalog/passages`. The agent often finds the documents first (with
`catalog_search` or `doc_search`) and then wants what those documents say.
The endpoint could narrow by dataset, place and date, but not by document,
so the agent's planned `asset_ids` parameter had nothing to call.

## Decision

`/passages` takes `asset_id`, repeated, up to 10 UUIDs. The view passes them
to `passages.search`, which keeps only those of the documents the other
filters chose. The chunk index then searches that shortlist, as it already
did for the whole list.

- **Within the other filters, not instead of them.** An id outside the place
  or dataset asked for is not let in, so the filters still mean what they
  say.
- **Up to 10:** the agent sends the handles of documents it has seen. A
  longer list isn't a narrowing.
- **An unknown or inactive id isn't an error.** It just isn't among the
  documents, like any filter that matches nothing.

## Consequences

- Additive. A request without `asset_id` behaves as before.
- `openapi.yaml` and the Orval client gain the parameter. The SPA doesn't
  use it yet.
