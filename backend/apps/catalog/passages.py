"""Deep search: the passages that best answer a question, grouped by document.

Two steps, the data platform's own (gobase `store.search_chunks`): the catalog
names the documents a question may be matched against, narrowed like any browse
— by place, by window, by dataset — and the chunk index ranks their passages by
how close they are in meaning (docs/adr/020). The question is already a vector
by the time it reaches here; embedding it is `godoc.embed`'s job.

Pages are counted from 1 on the way out. The index stores them from 0, as
MinerU numbers them; nothing above this module sees that.
"""

from . import chunks, kb


def search(
    vector,
    embedder_id: str,
    *,
    limit: int,
    per_document: int,
    dataset: str | None = None,
    bbox: list[float] | None = None,
    point: tuple[float, float] | None = None,
    area: str | None = None,
    coverage: str = "asset",
    ingested_after=None,
    ingested_before=None,
) -> list[dict]:
    """Up to `limit` documents, each with up to `per_document` passages, best first.

    A document ranks by its best passage. `limit * per_document` passages are
    asked for in all, so a document rich in close passages can crowd out
    weaker documents: the answer is "up to" `limit`, never padded.
    """
    documents = kb.chunked_documents(
        embedder_id=embedder_id,
        dataset=dataset,
        bbox=bbox,
        point=point,
        area=area,
        coverage=coverage,
        ingested_after=ingested_after,
        ingested_before=ingested_before,
    )
    by_asset = {str(document["asset_id"]): document for document in documents}
    if not by_asset:
        return []

    # One table per embedder, but grouped by table all the same, as the data
    # platform does: two silver roots would be two tables.
    by_table: dict[str, list[str]] = {}
    for asset_id, document in by_asset.items():
        by_table.setdefault(document["chunks_uri"], []).append(asset_id)

    hits: list[dict] = []
    for chunks_uri, asset_ids in by_table.items():
        hits.extend(chunks.search(chunks_uri, vector, asset_ids, k=limit * per_document))
    hits.sort(key=lambda hit: (-(hit["score"] or 0.0), hit["asset_id"], hit["chunk_id"]))

    # Insertion order is rank order: a document enters at its best passage. A
    # passage of a document not in scope is skipped: the prefilter should keep
    # them out, but a table can hold rows of a catalog that no longer exists
    # (gobase diary, 2026-10-19), and those are nobody's answer.
    grouped: dict[str, list[dict]] = {}
    for hit in hits:
        asset_id = str(hit["asset_id"])
        if asset_id not in by_asset:
            continue
        rows = grouped.setdefault(asset_id, [])
        if len(rows) < per_document:
            rows.append(hit)

    results = []
    for asset_id, rows in list(grouped.items())[:limit]:
        document = {key: value for key, value in by_asset[asset_id].items() if key != "chunks_uri"}
        results.append(
            {**document, "score": rows[0]["score"], "passages": [_passage(hit) for hit in rows]}
        )
    return results


def _passage(hit: dict) -> dict:
    """One passage in portal terms, pages from 1."""
    return {
        "chunk_id": hit["chunk_id"],
        "text": hit.get("text") or "",
        "heading_path": list(hit.get("heading_path") or []),
        "page_start": _page(hit.get("page_start")),
        "page_end": _page(hit.get("page_end")),
        "pages_with_boxes": sorted({box["page"] + 1 for box in hit.get("bboxes") or []}),
        "chunk_type": hit.get("chunk_type") or "text",
        "score": hit["score"],
    }


def _page(index) -> int | None:
    """A 0-based page index as a reader counts it, or None when the index has none."""
    return index + 1 if index is not None else None
