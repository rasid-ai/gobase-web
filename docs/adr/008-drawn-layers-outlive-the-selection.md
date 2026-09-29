# ADR-008: Drawn layers outlive the selection, and a modality endpoint may name its modality

**Status:** Accepted · 2026-09-11

## Context

specs/map.md describes point inspection as one thing: click a point, pick
an asset, see its metadata and footprint, clear it. Clearing removes "that
asset's metadata, its footprint, and any vector or raster layer drawn for
it". A layer, in that description, belongs to the selection.

GP-4 and GP-5 add the features themselves — the rows inside the asset's
GeoParquet file, not just its outline. That changes what a layer is for.
The catalog holds 22 vector assets over one city; they are OpenStreetMap
extracts of the same place, split by theme — roads, water, railways,
buildings. The reason to draw them is to see them together.

Tying a layer to the selection makes that impossible: picking the second
asset erases the first. The spec's model was written when a layer was an
outline that described the selected asset. It no longer is.

Separately, GP-4 needs to identify a vector asset. `public.assets` holds
every modality, and reading GeoParquet only makes sense for one of them.
But specs/map.md says data types "come from the knowledge base and are
never enumerated in portal code".

## Decision

**Drawn layers are not part of the selection.** They live in their own
store, are listed in their own panel, and are removed only by that panel's
controls. Selecting another asset, clearing a selection, closing the asset
panel and clicking a new point all leave them alone.

Consequences that follow, and are not optional:

- The layer store must sit above anything that can reset it. It wraps the
  workspace (`LayersProvider` in WorkspacePage.tsx), not a subtree that
  re-mounts when the selection changes.
- Drawing needs its own control. The row click still selects — it shows
  metadata — and a separate control draws. One action must not force the
  other, because they now have different lifetimes.
- Hiding a layer is a paint change, never a refetch. The features are
  already in the store.
- There must be a way out. Per-layer remove and a clear-all, or the map
  silently accumulates layers a user cannot get rid of.

**A modality-specific endpoint may name its own modality.** The vector
data endpoint filters `modality = 'vector'` in `catalog.py`, in one
statement, and says why. Other modalities get their own endpoints reading
their own tables rather than one endpoint that branches.

The original rule stands everywhere else, and it was about something
different: the portal must not hold a closed list of data types for
grouping, labelling or display, because the knowledge base owns that list
and it grows. Naming one modality in the endpoint that exists to serve it
is not that. The endpoint would be wrong, not merely unhelpful, if it read
a raster.

## Rejected

**Layers tied to the selection, as specs/map.md says.** One less concept,
one less panel, and clearing is obvious because there is only one thing to
clear. Rejected because comparison is the reason to draw features at all,
and this makes comparison impossible. The trade is real: the map can now
hold state the asset panel does not explain, and a user who draws six
layers and clicks elsewhere has no indication of where they came from.
That is what the layers panel is for, and it is why remove and clear-all
are not optional.

**A `v_queryable_layers` join instead of naming the modality.** The view
already encodes "active asset with a Parquet file", so a vector asset is
exactly a row in it and no modality string appears anywhere. Rejected
because `assets.source_uri` already holds the same URI as
`geo_layers.parquet_uri` — verified identical for all 22 active assets —
so the join buys nothing but a second table, and "has a Parquet file" is a
weaker statement than "is vector" that would quietly start matching
whatever the data platform adds next.

## Revisit when

A second modality gets a data endpoint. Two endpoints each naming their
own modality is the intended shape; three or more that branch internally
is the sign this was the wrong cut. Also revisit if a drawn layer needs to
survive a page reload — that needs the layer set in the URL or in
`portal`, and neither is designed here.
