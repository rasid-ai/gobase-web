"""The only module that knows the knowledge base's tables and columns.

Everything above this speaks in portal terms. The schema this maps onto is
documented in context/integrations/kb.md; docs/adr/002 explains why the access
is read-only, unmanaged, and never joined to `portal` in SQL.

Raw SQL rather than unmanaged models on purpose: the metadata a caller gets
back has no fixed field set (specs/map.md), the coverage predicate is
PostGIS-specific, and `KB_APP_LABELS` in config/db_router.py stays empty so the
router's refusal to write or migrate `kb` remains absolute.
"""

import json

from django.db import connections

KB = "kb"

# Superseded and failed rows stay in `assets`, so every read filters on status.
# The (modality, status) index exists for exactly this pairing.
_COVERING_POINT = """
    SELECT asset_id, modality, source_uri, format, summary, time_start, time_end
    FROM assets
    WHERE status = 'active'
      AND ST_Intersects(extent, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    ORDER BY modality, source_uri
"""

_ASSET = """
    SELECT asset_id, modality, source_uri, format, summary, topic_path::text,
           bytes, time_start, time_end, ingested_at,
           ST_AsGeoJSON(extent) AS footprint
    FROM assets
    WHERE asset_id = %s AND status = 'active'
"""

_VECTOR_LAYERS = """
    SELECT layer_name, geometry_type, native_crs, feature_count, columns
    FROM geo_layers
    WHERE asset_id = %s
    ORDER BY layer_name
"""

_RASTER_LAYERS = """
    SELECT layer_name, native_crs, width, height, band_count, dtype,
           pixel_size_x, pixel_size_y, nodata, compression, is_cog,
           overview_count, bands, tags, stats
    FROM geo_raster_layers
    WHERE asset_id = %s
    ORDER BY layer_name
"""


def _rows(sql, params):
    """Run a read against `kb` and return dicts keyed by column name."""
    with connections[KB].cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def assets_covering_point(lon: float, lat: float) -> list[dict]:
    """Active catalog assets whose coverage contains the point.

    Ordered by data type so the caller can group without re-sorting. An
    uncovered point yields an empty list, which is a valid answer and not an
    error (specs/map.md).
    """
    return _rows(_COVERING_POINT, [lon, lat])


def asset_detail(asset_id) -> dict | None:
    """One active asset's metadata and footprint, or None if there is no such asset.

    The metadata dict is deliberately shaped by the data, not by a schema: null
    columns are dropped and layer detail is merged in, so a raster and a
    document come back with different keys (specs/map.md).
    """
    found = _rows(_ASSET, [str(asset_id)])
    if not found:
        return None
    row = found[0]

    # ST_AsGeoJSON hands back a string; callers want the geometry itself.
    footprint = row.pop("footprint")
    footprint = json.loads(footprint) if footprint else None
    asset_uuid = row.pop("asset_id")
    modality = row.pop("modality")

    metadata = {key: value for key, value in row.items() if value is not None}
    for layer in _layers_for(asset_uuid, modality):
        metadata.update(layer)

    return {
        "asset_id": asset_uuid,
        "data_type": modality,
        "metadata": metadata,
        "footprint": footprint,
    }


def _layers_for(asset_id, modality: str) -> list[dict]:
    """Layer rows for an asset, keyed for a flat metadata view.

    A single layer merges its columns in directly; several layers are prefixed
    with the layer name so nothing collides.
    """
    sql = _RASTER_LAYERS if modality == "raster" else _VECTOR_LAYERS
    layers = _rows(sql, [str(asset_id)])

    merged = []
    for layer in layers:
        name = layer.pop("layer_name", None)
        present = {key: value for key, value in layer.items() if value is not None}
        if len(layers) > 1 and name:
            present = {f"{name}.{key}": value for key, value in present.items()}
        elif name:
            present["layer_name"] = name
        merged.append(present)
    return merged
