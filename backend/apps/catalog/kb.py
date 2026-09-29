"""The only module that knows the knowledge base's tables and columns.

Everything above this speaks in portal terms. The schema this maps onto is
documented in context/integrations/kb.md; docs/adr/002 explains why the access
is read-only, unmanaged, and never joined to `portal` in SQL.

Raw SQL rather than unmanaged models on purpose: the metadata a caller gets
back has no fixed field set (specs/map.md), the coverage predicate is
PostGIS-specific, and `KB_APP_LABELS` in config/db_router.py stays empty so the
router's refusal to write or migrate `kb` remains absolute.

It lives in `apps.catalog` because two apps read the knowledge base now: the
catalog browses it, for the Assets page and the map's panel alike, and the Map
resolves one asset's detail and lake path against it (docs/adr/010,
docs/adr/016).
"""

import json
from itertools import groupby

from django.db import connections

KB = "kb"

# `assets` has no name column and `summary` is empty across the live catalog,
# so the portal derives one: the basename of `source_uri` without its extension
# (docs/adr/010). Written once because the same expression has to serve the
# text filter, the sort, and what the client displays — and an output alias is
# not visible to WHERE, which is why the browse query is a CTE.
_DERIVED_NAME = r"regexp_replace(split_part(source_uri, '/', -1), '\.[^.]*$', '')"

# `dataset` is a folder name — `points_of_interest_hotsom` — and people read
# a label: "Points of interest hotsom" (docs/adr/016). camelCase is split,
# underscores, hyphens and runs of space become one space, and the result is
# in sentence case. Computed here rather than in the interface so that search
# matches the words on the screen. Spelling is the data's own: the knowledge
# base is read-only, so `goverment` stays "Goverment".
_SPACED_DATASET = (
    r"lower(btrim(regexp_replace("
    r"regexp_replace(dataset, '([a-z0-9])([A-Z])', '\1 \2', 'g'), '[_\s-]+', ' ', 'g')))"
)
_DATASET_LABEL = f"upper(left({_SPACED_DATASET}, 1)) || substr({_SPACED_DATASET}, 2)"

# Every piece of catalog text about one asset, for the search box (docs/adr/016):
# the file's name, its dataset and label, topic, format, data type and summary,
# then each layer's name — with the column names of a vector layer and the tag
# values of a raster one. Tag keys are left out: every raster has a `year`, so
# matching keys would make "year" find all of them.
#
# The pieces are joined by the unit separator, a character nobody types, so a
# search cannot match across the seam between two fields — "vector boundaries"
# must not match because one field ends in "vector" and the next starts with
# "boundaries".
#
# Values only ever reach it through the database's own JSON functions, never
# by casting a whole document to text, which would put `"name"` and `"dtype"`
# into every vector asset's text.
_SEARCH_TEXT = rf"""concat_ws(E'\x1f',
            split_part(source_uri, '/', -1), dataset, {_DATASET_LABEL},
            topic_path::text, format, modality, summary,
            (SELECT string_agg(concat_ws(E'\x1f', layer.layer_name,
                    (SELECT string_agg(col ->> 'name', E'\x1f')
                     FROM jsonb_array_elements(CASE WHEN jsonb_typeof(layer.columns) = 'array'
                                                    THEN layer.columns ELSE '[]'::jsonb END) col)),
                    E'\x1f')
             FROM geo_layers layer WHERE layer.asset_id = assets.asset_id),
            (SELECT string_agg(concat_ws(E'\x1f', raster.layer_name,
                    (SELECT string_agg(tag #>> '{{}}', E'\x1f')
                     FROM jsonb_path_query(raster.tags, 'strict $.**') tag
                     WHERE jsonb_typeof(tag) IN ('string', 'number', 'boolean'))),
                    E'\x1f')
             FROM geo_raster_layers raster WHERE raster.asset_id = assets.asset_id))"""

_ASSET = f"""
    SELECT asset_id, {_DERIVED_NAME} AS name, modality, source_uri, format, dataset,
           summary, topic_path::text, bytes, time_start, time_end, ingested_at,
           ST_AsGeoJSON(extent) AS footprint
    FROM assets
    WHERE asset_id = %s AND status = 'active'
"""

# The lake path for one vector asset. `assets` holds every modality, so this
# is the one place the portal names a modality: the endpoint it serves is
# vector-only by definition (specs/map.md, docs/adr/008). `source_uri` is the
# full s3:// URI of the GeoParquet, bucket included.
_VECTOR_SOURCE_URI = """
    SELECT source_uri
    FROM assets
    WHERE asset_id = %s AND status = 'active' AND modality = 'vector'
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

# Superseded and failed rows stay in `assets`, so every read filters on status.
# The (modality, status) index exists for exactly this pairing.
_CATALOG_HEAD = f"""
    WITH catalog AS (
        SELECT asset_id, modality, format, topic_path::text AS topic_path,
               bytes, summary, time_start, time_end, ingested_at,
               ST_XMin(extent) AS min_lon, ST_YMin(extent) AS min_lat,
               ST_XMax(extent) AS max_lon, ST_YMax(extent) AS max_lat,
               {_DERIVED_NAME} AS name,
               dataset, {_DATASET_LABEL} AS dataset_label,
               {_SEARCH_TEXT} AS search
        FROM assets
        WHERE status = 'active'
"""

# The three places a caller can narrow the catalog to. A searched place is a
# box; a clicked point and a drawn polygon come from the map (docs/adr/016).
# The WKT reaches here already validated by `AreaField`.
_BBOX = "          AND ST_Intersects(extent, ST_MakeEnvelope(%s, %s, %s, %s, 4326))\n"
_POINT = "          AND ST_Intersects(extent, ST_SetSRID(ST_MakePoint(%s, %s), 4326))\n"
_AREA = "          AND ST_Intersects(extent, ST_GeomFromText(%s, 4326))\n"


def _catalog(bbox=None, point=None, area=None) -> tuple[str, list]:
    """The browse CTE, optionally narrowed to one place.

    The place belongs inside the CTE rather than in `_where`, and that placement
    is the whole design: `asset_list` runs three reads off this one CTE, so
    every one of them -- the page, the total, and the per-type counts -- is
    narrowed together and cannot drift apart. A page showing nothing beside a
    filter rail still counting the whole catalog reads as a broken page.

    `ST_Intersects` rather than the `&&` box operator: PostGIS puts a bounding
    box index condition in front of it anyway, so the GiST index on `extent` is
    used either way, and the precise test stays correct if extents ever become
    real footprints instead of the envelopes they are today.

    `ST_MakeEnvelope` takes its corners in the order the `bbox` parameter
    already carries them -- min_lon, min_lat, max_lon, max_lat -- so nothing is
    reordered anywhere between the URL and the bind. A point is `(lon, lat)`,
    which is `ST_MakePoint`'s order too.
    """
    given = [place for place in (bbox, point, area) if place is not None]
    if len(given) > 1:
        # The serializers refuse this first; reaching here is a caller's bug,
        # and ANDing two places would answer a question nobody asked.
        raise ValueError("Narrow the catalog to one place at most.")

    if bbox is not None:
        return _CATALOG_HEAD + _BBOX + "    )\n", list(bbox)
    if point is not None:
        return _CATALOG_HEAD + _POINT + "    )\n", list(point)
    if area is not None:
        return _CATALOG_HEAD + _AREA + "    )\n", [area]
    return _CATALOG_HEAD + "    )\n", []


# Sort keys are looked up, never interpolated from what a caller typed. An
# unknown key raises rather than reaching SQL.
#
# Every ordering ends in `asset_id`. That is not decoration: the whole live
# catalog was ingested in one run and shares a single `ingested_at`, so without
# a tiebreak the database may return the rows in any order and offset paging
# repeats some and skips others.
SORTS = {
    "-ingested_at": "ingested_at DESC",
    "ingested_at": "ingested_at ASC",
    "name": "name ASC",
    "-name": "name DESC",
    "data_type": "modality ASC",
}

# ILIKE reads `%` and `_` as wildcards, and asset names are full of
# underscores, so what the user typed is escaped and matched literally.
_LIKE_ESCAPE = str.maketrans({"\\": r"\\", "%": r"\%", "_": r"\_"})


# Postgres type ids for `json` and `jsonb`.
_JSON_TYPES = {114, 3802}


def _rows(sql, params):
    """Run a read against `kb` and return dicts keyed by column name.

    JSON columns come back as the values they hold. Django sets psycopg 3 up to
    hand `json` and `jsonb` over as text — its own JSONField decodes them — so
    a raw cursor gets strings, and `columns`, `bands`, `tags` and `stats` used
    to reach the client as a line of JSON text instead of a list or an object.
    Decoded here by column type, not by name, so a new JSON column needs
    nothing.
    """
    with connections[KB].cursor() as cursor:
        cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        decoded = [column[1] in _JSON_TYPES for column in cursor.description]
        return [
            {
                name: json.loads(value) if is_json and isinstance(value, str) else value
                for name, is_json, value in zip(columns, decoded, row, strict=True)
            }
            for row in cursor.fetchall()
        ]


def asset_list(
    *,
    q: str | None = None,
    data_types: list[str] | None = None,
    dataset: str | None = None,
    bbox: list[float] | None = None,
    point: tuple[float, float] | None = None,
    area: str | None = None,
    ingested_after=None,
    ingested_before=None,
    sort: str = "-ingested_at",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """One page of the catalog, the total behind it, and the counts by type.

    Three reads rather than one: the page, how many rows match, and how many
    rows each data type would match. The last deliberately ignores the caller's
    own `data_types` selection — counts that collapse to the thing you already
    picked tell you nothing about what else is there (docs/adr/010). That is
    the one axis excluded; `q`, the dataset, the ingestion window and the place
    all narrow the counts, because each of them describes a different catalog
    to be counted.

    The place is bound by the CTE and every filter after it by `_where`, so each
    read's parameters are the place's first and the rest after. Getting that
    order wrong binds the numbers to the wrong placeholders and returns a wrong
    answer rather than raising, which is why `test_browse_query` checks it.
    """
    catalog, place = _catalog(bbox, point, area)

    where, params = _where(q, data_types, ingested_after, ingested_before, dataset)
    page = _rows(
        f"{catalog} SELECT * FROM catalog{where} ORDER BY {_order_by(sort)} LIMIT %s OFFSET %s",
        [*place, *params, limit, offset],
    )
    total = _rows(f"{catalog} SELECT count(*) AS count FROM catalog{where}", [*place, *params])

    counted_where, counted_params = _where(q, None, ingested_after, ingested_before, dataset)
    counts = _rows(
        f"{catalog} SELECT modality, count(*) AS count FROM catalog{counted_where} "
        "GROUP BY modality ORDER BY modality",
        [*place, *counted_params],
    )

    return {
        "count": total[0]["count"],
        "results": [_list_item(row) for row in page],
        "data_type_counts": [
            {"data_type": row["modality"], "count": row["count"]} for row in counts
        ],
    }


def _order_by(sort: str) -> str:
    """The ordering for one sort key, always ending in a tiebreak.

    `asset_id` last is not decoration. The whole live catalog was ingested in
    one run and shares a single `ingested_at`, so on rows the sort cannot tell
    apart the database may return any order it likes — and offset paging then
    repeats some rows and skips others.
    """
    return f"{SORTS[sort]}, asset_id"


def _where(q, data_types, ingested_after, ingested_before, dataset=None) -> tuple[str, list]:
    """The browse filters as a WHERE clause and its parameters.

    Every filter is optional and absent means "no restriction", so no filter at
    all yields an empty string rather than a clause that is always true.

    `q` matches the asset's whole searchable text, not only its name
    (docs/adr/016). It is one literal piece: what was typed must appear, as
    typed, inside one field. `dataset` is an exact value, because it comes from
    a dataset the caller picked, not from a box.
    """
    clauses, params = [], []
    if q:
        clauses.append(r"search ILIKE %s ESCAPE '\'")
        params.append(_contains(q))
    if data_types:
        clauses.append("modality = ANY(%s)")
        params.append(list(data_types))
    if dataset:
        clauses.append("dataset = %s")
        params.append(dataset)
    if ingested_after is not None:
        clauses.append("ingested_at >= %s")
        params.append(ingested_after)
    if ingested_before is not None:
        clauses.append("ingested_at < %s")
        params.append(ingested_before)

    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _contains(text: str) -> str:
    """An ILIKE pattern matching `text` anywhere, with its wildcards disarmed.

    The field separator is dropped from what was typed, or a pasted one would
    match across the seam that `_SEARCH_TEXT` puts it there to guard.
    """
    return f"%{text.replace(chr(0x1F), '').translate(_LIKE_ESCAPE)}%"


def _list_item(row: dict) -> dict:
    """One catalog row in portal terms.

    Fixed shape, unlike `asset_detail`: a browse list shows the same fields for
    every asset, so a missing value is null rather than an absent key.
    """
    corners = [row["min_lon"], row["min_lat"], row["max_lon"], row["max_lat"]]
    return {
        "asset_id": row["asset_id"],
        "name": row["name"],
        "data_type": row["modality"],
        "format": row["format"],
        "dataset": row["dataset"],
        "dataset_label": row["dataset_label"],
        "topic_path": row["topic_path"],
        "bytes": row["bytes"],
        # An asset with no coverage is possible — a document, say — and has no
        # box to draw.
        "bbox": corners if None not in corners else None,
        "summary": row["summary"],
        "time_start": row["time_start"],
        "time_end": row["time_end"],
        "ingested_at": row["ingested_at"],
    }


def dataset_list(
    *,
    q: str | None = None,
    bbox: list[float] | None = None,
    point: tuple[float, float] | None = None,
    area: str | None = None,
    ingested_after=None,
    ingested_before=None,
) -> list[dict]:
    """The datasets holding at least one matching asset, with what is in each.

    Off the same CTE as `asset_list`, so a dataset's count here is exactly the
    number of assets the caller will find on opening it with the same place and
    window. `q` matches the dataset's own name and label only — never its
    files' metadata. Searching datasets and searching files are two questions,
    and each level of the interface asks one (docs/adr/016).

    An asset whose `dataset` is null belongs to no dataset and is left out
    rather than gathered under a name the portal made up. The data platform
    labels every active asset on every run, so a null is a gap between two of
    its steps, and the asset still appears in the flat list.

    Not paged: there is one dataset per top folder of the raw bucket, which is
    eleven today. Ordered by label, the thing a person reads.
    """
    catalog, place = _catalog(bbox, point, area)

    where, params = _where(None, None, ingested_after, ingested_before)
    clauses = ["dataset IS NOT NULL"]
    if q:
        clauses.append(r"(dataset ILIKE %s ESCAPE '\' OR dataset_label ILIKE %s ESCAPE '\')")
        params += [_contains(q), _contains(q)]
    named = " AND ".join(clauses)
    where = f"{where} AND {named}" if where else f" WHERE {named}"

    rows = _rows(
        f"{catalog} SELECT dataset, dataset_label, modality, count(*) AS count "
        f"FROM catalog{where} "
        "GROUP BY dataset, dataset_label, modality ORDER BY dataset_label, dataset, modality",
        [*place, *params],
    )

    datasets = []
    for (dataset, label), types in groupby(
        rows, key=lambda row: (row["dataset"], row["dataset_label"])
    ):
        counts = [{"data_type": row["modality"], "count": row["count"]} for row in types]
        datasets.append(
            {
                "dataset": dataset,
                "label": label,
                "count": sum(item["count"] for item in counts),
                "data_type_counts": counts,
            }
        )
    return datasets


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
    # The same derived name the browse list shows, so a drawn layer is called
    # the same thing whichever panel drew it.
    name = row.pop("name")

    metadata = {key: value for key, value in row.items() if value is not None}
    for layer in _layers_for(asset_uuid, modality):
        metadata.update(layer)

    return {
        "asset_id": asset_uuid,
        "name": name,
        "data_type": modality,
        "metadata": metadata,
        "footprint": footprint,
    }


def vector_source_uri(asset_id) -> str | None:
    """The lake URI of an active vector asset, or None if there is no such asset.

    None covers all three misses the caller treats alike: no such id, a
    superseded or failed row, and an asset of another modality. Each is a 404 —
    the portal does not tell one apart from the other.
    """
    found = _rows(_VECTOR_SOURCE_URI, [str(asset_id)])
    return found[0]["source_uri"] if found else None


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
