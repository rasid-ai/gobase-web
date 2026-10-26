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

# A document is the exception. Its `source_uri` is the parsed bundle in silver
# (`<stem>.bundle.zip`), and the thing a person recognises is the PDF it was
# parsed from, which `doc_documents.pdf_uri` names in bronze. So a document is
# called after its PDF, extension kept (docs/adr/017). One whose PDF the
# catalog does not record — a bundle loaded without its source stamp — falls
# back to the bundle's stem, with the `.bundle` the derived name leaves behind
# taken off too.
_PDF_NAME = "split_part(doc.pdf_uri, '/', -1)"
_NAME = rf"COALESCE({_PDF_NAME}, regexp_replace({_DERIVED_NAME}, '\.bundle$', ''))"

# And a document's format is its file's — `pdf` — not the parser that read it,
# which is what `assets.format` records (`mineru`). The parser is still worth
# knowing, so the detail carries it as `parser`; the list shows the file.
_FORMAT = rf"COALESCE(lower(substring({_PDF_NAME} from '\.([^.]+)$')), format)"

# Every catalog read joins the document row. It is a LEFT JOIN, so the other
# modalities are untouched; it does mean a knowledge base without
# `doc_documents` fails every read (context/integrations/kb.md).
_DOCUMENTS = "LEFT JOIN doc_documents doc ON doc.asset_id = assets.asset_id"

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
# a document's PDF name and title, then each layer's name — with the column
# names of a vector layer and the tag values of a raster one. Tag keys are left
# out: every raster has a `year`, so matching keys would make "year" find all
# of them.
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
            {_PDF_NAME}, doc.title,
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
    SELECT assets.asset_id, {_NAME} AS name, modality, source_uri, {_FORMAT} AS format, dataset,
           summary, topic_path::text, bytes, time_start, time_end, ingested_at,
           doc.title, doc.pages,
           CASE WHEN doc.asset_id IS NOT NULL THEN format END AS parser,
           ST_AsGeoJSON(extent) AS footprint
    FROM assets {_DOCUMENTS}
    WHERE assets.asset_id = %s AND status = 'active'
"""

# The lake path for one vector asset. `assets` holds every modality, so the
# two reads below are the only places the portal names one: each serves an
# endpoint that is one modality by definition (specs/map.md, docs/adr/008).
# `source_uri` is the full s3:// URI of the GeoParquet, bucket included.
_VECTOR_SOURCE_URI = """
    SELECT source_uri
    FROM assets
    WHERE asset_id = %s AND status = 'active' AND modality = 'vector'
"""

# The PDF behind one document, in bronze: `pdf_uri` is a full s3:// URI too.
# `content_hash` is the PDF's own sha256, which is what makes it a strong ETag
# (docs/adr/017).
_DOCUMENT_PDF = """
    SELECT doc.pdf_uri, content_hash, split_part(doc.pdf_uri, '/', -1) AS filename
    FROM assets JOIN doc_documents doc ON doc.asset_id = assets.asset_id
    WHERE assets.asset_id = %s AND status = 'active' AND modality = 'document'
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
        SELECT assets.asset_id, modality, {_FORMAT} AS format, topic_path::text AS topic_path,
               bytes, summary, time_start, time_end, ingested_at,
               ST_XMin(extent) AS min_lon, ST_YMin(extent) AS min_lat,
               ST_XMax(extent) AS max_lon, ST_YMax(extent) AS max_lat,
               {_NAME} AS name,
               dataset, {_DATASET_LABEL} AS dataset_label,
               doc.title AS document_title, doc.pages AS document_pages,
               doc.pdf_uri IS NOT NULL AS document_pdf,
               {_SEARCH_TEXT} AS search
        FROM assets {_DOCUMENTS}
        WHERE status = 'active'
"""

# The three places a caller can narrow the catalog to. A searched place is a
# box; a clicked point and a drawn polygon come from the map (docs/adr/016).
# The WKT reaches here already validated by `AreaField`.
_BBOX = "ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
_POINT = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
_AREA = "ST_GeomFromText(%s, 4326)"

# What the place is compared with (docs/adr/019). `asset`: the asset's own
# coverage, the map's question. `dataset`: its dataset's, the Assets page's. A
# dataset covers what any of its active assets covers, so every file of a
# dataset in the place comes with it, documents and others with no coverage of
# their own included. An asset with no dataset has only its own to go by.
COVERAGES = ("asset", "dataset")
_BY_ASSET = "          AND ST_Intersects(extent, {place})\n"
_BY_DATASET = """          AND (assets.dataset IN (SELECT covering.dataset FROM assets covering
                                  WHERE covering.status = 'active'
                                    AND ST_Intersects(covering.extent, {place}))
               OR (assets.dataset IS NULL AND ST_Intersects(extent, {place})))
"""


def _catalog(bbox=None, point=None, area=None, coverage="asset") -> tuple[str, list]:
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

    By dataset, the place appears twice in the SQL, so its parameters are bound
    twice. A dataset's coverage is the union of its assets' rather than the box
    around them: the box around two far-apart files covers everything between
    them, which the dataset holds nothing of.
    """
    given = [place for place in (bbox, point, area) if place is not None]
    if len(given) > 1:
        # The serializers refuse this first; reaching here is a caller's bug,
        # and ANDing two places would answer a question nobody asked.
        raise ValueError("Narrow the catalog to one place at most.")
    if coverage not in COVERAGES:
        raise ValueError(f"Unknown coverage: {coverage!r}.")

    if bbox is not None:
        sql, params = _BBOX, list(bbox)
    elif point is not None:
        sql, params = _POINT, list(point)
    elif area is not None:
        sql, params = _AREA, [area]
    else:
        return _CATALOG_HEAD + "    )\n", []

    if coverage == "dataset":
        return _CATALOG_HEAD + _BY_DATASET.format(place=sql) + "    )\n", params * 2
    return _CATALOG_HEAD + _BY_ASSET.format(place=sql) + "    )\n", params


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
    coverage: str = "asset",
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
    catalog, place = _catalog(bbox, point, area, coverage)

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
        "document": _document(row),
    }


def _document(row: dict) -> dict | None:
    """What a document carries beyond the shared columns, or None for any other type.

    Null rather than absent, like every other value a list row may lack. `pdf`
    says whether the catalog records the PDF, and so whether the PDF endpoint
    can serve it; the client offers to open it only when it can.
    """
    if row["modality"] != "document":
        return None
    return {
        "title": row.get("document_title"),
        "pages": row.get("document_pages"),
        "pdf": bool(row.get("document_pdf")),
    }


def dataset_list(
    *,
    q: str | None = None,
    bbox: list[float] | None = None,
    point: tuple[float, float] | None = None,
    area: str | None = None,
    coverage: str = "asset",
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
    catalog, place = _catalog(bbox, point, area, coverage)

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


def document_pdf(asset_id) -> dict | None:
    """Where an active document's PDF is, or None if there is nothing to serve.

    `pdf_uri`, `filename` and `content_hash`. None covers every miss alike —
    no such id, a superseded row, another modality, and a document whose PDF
    the catalog never recorded — because each is the same 404 to the caller.

    The path can be stale: after a PDF is moved in bronze the data platform
    re-stamps the bundle but leaves `pdf_uri` until the next reindex, on
    purpose (gobase `orchestration/tests/test_assets.py`). The lake then
    answers 404 and the endpoint 502.
    """
    found = _rows(_DOCUMENT_PDF, [str(asset_id)])
    if not found or found[0]["pdf_uri"] is None:
        return None
    return found[0]


# Similarity, for the map's Semantic mode (docs/adr/018). The browse CTE again,
# so a match is exactly a list row, joined to the card embedded by the same
# model as the question. Cards exist for documents today, and the join names
# no modality on purpose: a video's or an image's card would come back the
# same way. `<=>` is cosine distance and the cards are unit vectors, so this
# is the ranking the data platform's own search gives
# (gobase/modalities/document/store.py). A sequential scan, which is fine
# until there is an ANN index — the data platform adds one per embedder when
# the table earns it.
#
# The dataset's extent rides beside each match: a document has no coverage of
# its own, and "where is this about" is answered by the dataset it sits in.
_SIMILAR = """
    SELECT catalog.*, 1 - (card.vector <=> %s::vector) AS score,
           ST_XMin(span.box) AS dataset_min_lon, ST_YMin(span.box) AS dataset_min_lat,
           ST_XMax(span.box) AS dataset_max_lon, ST_YMax(span.box) AS dataset_max_lat
    FROM catalog
    JOIN doc_cards card ON card.asset_id = catalog.asset_id AND card.embedder_id = %s
    LEFT JOIN LATERAL (
        SELECT ST_Extent(extent) AS box FROM assets span
        WHERE span.dataset = catalog.dataset AND span.status = 'active'
    ) span ON true
    ORDER BY score DESC, catalog.asset_id
    LIMIT %s
"""


def _vector_literal(vector) -> str:
    """A vector in pgvector's text form, `[0.1,0.2,...]`, bound as text and cast in SQL.

    The way the data platform binds one (gobase `core/results.py`): the driver
    sees a string, and no pgvector adapter is needed.
    """
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def similar_assets(vector, embedder_id: str, limit: int) -> list[dict]:
    """The assets whose card is closest to `vector`, best first.

    `embedder_id` must name the model that produced `vector`: the cards of any
    other model are left out rather than ranked against a vector they cannot
    be compared with. No place — this is meaning only (docs/adr/018).
    """
    catalog, place = _catalog()
    rows = _rows(f"{catalog}{_SIMILAR}", [*place, _vector_literal(vector), embedder_id, limit])
    return [_similar_item(row) for row in rows]


def _similar_item(row: dict) -> dict:
    """A list row, plus how well it matched and where its dataset is."""
    corners = [
        row["dataset_min_lon"],
        row["dataset_min_lat"],
        row["dataset_max_lon"],
        row["dataset_max_lat"],
    ]
    return {
        **_list_item(row),
        "score": float(row["score"]),
        # The same rule as a row's own bbox: no coverage anywhere in the
        # dataset is null, not a box.
        "dataset_bbox": corners if None not in corners else None,
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
