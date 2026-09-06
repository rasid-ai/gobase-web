# Project Overview

**Geo Portal** is an internal web application that makes the geospatial
knowledge base usable through conversation and a map. It is built by a
subcontractor for the contracting team, and its users are that team.

The data platform (separate repo) ingests heterogeneous files — satellite
imagery, shapefiles, documents, spreadsheets — into a queryable knowledge
base on S3 and Postgres. This application is where people ask questions of
that knowledge base and see the answers.

**Why it exists:** So the team can find out what data exists and what it says — by asking, not by writing SQL or opening GIS tools.

## The two pages

**Map** — the main workspace: a chat panel and the map side by side.
1. Natural-language questions answered across all sources at once —
   documents, tabular data, and imagery metadata combined — with answers
   citing the underlying assets.
2. Question results display on the map when the answer includes a vector
   layer.
3. Click a point to see what data covers it — assets grouped by type,
   with metadata and footprints.
4. Select an area to scope a question spatially ("ask about here").

**Runs** — status and history of the ingestion pipeline runs (Dagster), so
the team can see data freshness and failures without server access.

## Out of scope

- Dashboards and analytics
- Public or client-external access
- Editing or uploading data (ingestion belongs to the data platform repo)
- Raster results displayed on the map (later phase)
