import math
import re
from typing import NamedTuple

from rest_framework import serializers

from .kb import SORTS


class BboxField(serializers.CharField):
    """An area as `min_lon,min_lat,max_lon,max_lat`, SRID 4326.

    One comma-joined parameter rather than four, so the same string travels
    from a page's `?bbox=` to the API unchanged and a link can be read by a
    person (docs/adr/011). A CharField subclass because DRF's ListField reads
    repeated keys, not commas — and because drf-spectacular then renders it as
    a plain string, which is what the URL actually holds.

    Kept in step with `parseBbox` in frontend/src/features/places/bbox.ts: the
    two validate the same thing on either side of the wire, and a link the
    client accepted must not be one the server rejects.
    """

    default_error_messages = {
        "shape": "bbox must be four numbers: min_lon,min_lat,max_lon,max_lat.",
        "range": "Longitudes must be between -180 and 180, latitudes between -90 and 90.",
        "order": "bbox minimums must not be greater than their maximums.",
    }

    def to_internal_value(self, data):
        parts = super().to_internal_value(data).split(",")
        if len(parts) != 4:
            self.fail("shape")
        try:
            corners = [float(part) for part in parts]
        except ValueError:
            self.fail("shape")
        # float() accepts "nan" and "inf", which reach PostGIS and mean nothing
        # there.
        if not all(math.isfinite(corner) for corner in corners):
            self.fail("shape")

        min_lon, min_lat, max_lon, max_lat = corners
        if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
            self.fail("range")
        if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            self.fail("range")
        # Equal corners are accepted: a zero-area box is a point-in-coverage
        # test, which is a real question. Only inside-out is refused.
        if min_lon > max_lon or min_lat > max_lat:
            self.fail("order")
        return corners


# The most distinct vertices a drawn area may have. The area travels in a GET
# query string, and on the production path the limit that binds is the host
# nginx's request-line buffer: 8 KB by default, which the vhost in
# infra/README.md does not change. Past it nginx answers 414 before the backend
# sees the request.
#
# Not gunicorn's 4094-byte `limit_request_line`, which is easy to assume and
# does not apply: the Dockerfile runs UvicornWorker, which parses HTTP itself.
# Measured — a 9.2 KB request line reached Django.
#
# A corner costs ~23 bytes URL-encoded at six decimals, so 100 corners is
# ~2.4 KB, under a third of nginx's limit with room for the rest of the URL. It
# also bounds the quadratic crossing check below. Hand-drawn polygons rarely
# pass 30 clicks.
MAX_AREA_VERTICES = 100

_POLYGON = re.compile(r"^\s*POLYGON\s*\(\(\s*([^()]*?)\s*\)\)\s*$", re.IGNORECASE)


class Area(NamedTuple):
    """A validated drawn area.

    `envelope` is carried alongside the WKT because the lake prunes with it:
    the covering-column range test takes a box, and parsing the polygon again
    in the reader would be a second parser for the same text.
    """

    wkt: str
    envelope: tuple[float, float, float, float]


def _orientation(a, b, c) -> int:
    """Which side of the line a→b the point c lies on: 1, -1, or 0 if on it."""
    turn = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (turn > 0) - (turn < 0)


def _within_box(a, b, c) -> bool:
    """For c already known to be on the line a→b: is it between a and b?"""
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _segments_meet(p1, p2, q1, q2) -> bool:
    """Whether two segments share any point at all, touching included."""
    o1, o2 = _orientation(p1, p2, q1), _orientation(p1, p2, q2)
    o3, o4 = _orientation(q1, q2, p1), _orientation(q1, q2, p2)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _within_box(p1, p2, q1))
        or (o2 == 0 and _within_box(p1, p2, q2))
        or (o3 == 0 and _within_box(q1, q2, p1))
        or (o4 == 0 and _within_box(q1, q2, p2))
    )


def _self_intersects(ring: list[tuple[float, float]]) -> bool:
    """Whether a closed ring crosses or touches itself anywhere.

    Every pair of edges is compared, which is quadratic and costs nothing at
    MAX_AREA_VERTICES. Neighbouring edges always share their joining vertex,
    so for them the only fault is the next edge doubling back along the
    previous one — a spike, which PostGIS also calls invalid.
    """
    edges = list(zip(ring, ring[1:], strict=False))
    count = len(edges)
    for i in range(count):
        a, b = edges[i]
        for j in range(i + 1, count):
            c, d = edges[j]
            if j == i + 1:
                shared, p, q = b, a, d
            elif i == 0 and j == count - 1:
                shared, p, q = a, b, c
            else:
                if _segments_meet(a, b, c, d):
                    return True
                continue
            # Two edges leaving one vertex overlap exactly when their far ends
            # are on one line through it and on the same side of it.
            if _orientation(p, shared, q) == 0:
                dot = (p[0] - shared[0]) * (q[0] - shared[0]) + (p[1] - shared[1]) * (
                    q[1] - shared[1]
                )
                if dot > 0:
                    return True
    return False


class AreaField(serializers.CharField):
    """A drawn polygon as WKT, `POLYGON((lon lat, lon lat, ...))`, SRID 4326.

    Parsed and checked here rather than handed to PostGIS and DuckDB as text,
    for one reason above all: **both engines answer a self-intersecting polygon
    silently**. Neither raises; each returns a count that is simply wrong. So
    an invalid shape has to be refused before either sees it.

    One ring only — no holes and no multipolygons, because the draw tool makes
    neither. The ring must be closed, as WKT requires; consecutive repeated
    points are dropped rather than refused, since they change nothing about
    the shape.

    Kept in step with frontend/src/features/workspace/drawnArea.ts and the
    draw tool's validation in DrawArea.tsx: the same corner cap and the same
    no-crossing rule on either side of the wire, so a shape the tool finished
    is never one the server refuses.
    """

    default_error_messages = {
        "shape": "area must be a single-ring polygon: POLYGON((lon lat, lon lat, ...)).",
        "number": "area coordinates must be finite numbers.",
        "range": "Longitudes must be between -180 and 180, latitudes between -90 and 90.",
        "closed": "area ring must end where it starts.",
        "few": "area needs at least three distinct corners.",
        "many": f"area may have at most {MAX_AREA_VERTICES} corners.",
        "flat": "area has no size: its corners lie on one line.",
        "crossing": "area crosses or touches itself; draw it without crossing lines.",
    }

    def to_internal_value(self, data):
        match = _POLYGON.match(super().to_internal_value(data))
        if not match:
            self.fail("shape")

        ring: list[tuple[float, float]] = []
        for pair in match.group(1).split(","):
            parts = pair.split()
            if len(parts) != 2:
                self.fail("shape")
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                self.fail("number")
            # float() takes "nan" and "inf", which mean nothing to either engine.
            if not (math.isfinite(lon) and math.isfinite(lat)):
                self.fail("number")
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                self.fail("range")
            if ring and ring[-1] == (lon, lat):
                continue
            ring.append((lon, lat))

        if len(ring) < 2 or ring[0] != ring[-1]:
            self.fail("closed")
        # The closing point repeats the first, so it is not a corner.
        corners = len(ring) - 1
        if corners < 3:
            self.fail("few")
        if corners > MAX_AREA_VERTICES:
            self.fail("many")

        # Every corner on one line, tested directly. Not by zero signed area:
        # a symmetric bowtie also sums to zero, because its two lobes cancel,
        # and it would then be refused for the wrong reason.
        first = ring[0]
        other = next((point for point in ring if point != first), first)
        if all(_orientation(first, other, point) == 0 for point in ring):
            self.fail("flat")
        if _self_intersects(ring):
            self.fail("crossing")

        lons = [lon for lon, _ in ring]
        lats = [lat for _, lat in ring]
        wkt = "POLYGON((" + ", ".join(f"{lon!r} {lat!r}" for lon, lat in ring) + "))"
        return Area(wkt=wkt, envelope=(min(lons), min(lats), max(lons), max(lats)))

    def to_representation(self, value):
        return value.wkt if isinstance(value, Area) else value


class AssetListQuerySerializer(serializers.Serializer):
    """The browse filters, validated before they reach the knowledge base.

    `sort` is a choice rather than free text because the value chooses a SQL
    ordering; `kb.SORTS` is the one list of orderings that exist, so the
    contract and the query cannot drift apart.
    """

    q = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Case-insensitive substring of the asset name.",
    )
    data_type = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        help_text="Repeatable. Omitted means every data type.",
    )
    ingested_after = serializers.DateTimeField(
        required=False, help_text="Ingested at or after this moment."
    )
    ingested_before = serializers.DateTimeField(
        required=False, help_text="Ingested strictly before this moment."
    )
    bbox = BboxField(
        required=False,
        help_text=(
            "Restrict to assets whose coverage overlaps this area: "
            "min_lon,min_lat,max_lon,max_lat, SRID 4326."
        ),
    )
    sort = serializers.ChoiceField(
        choices=sorted(SORTS),
        default="-ingested_at",
        help_text="A leading minus reverses the order.",
    )
    limit = serializers.IntegerField(default=50, min_value=1, max_value=200)
    offset = serializers.IntegerField(default=0, min_value=0)


class AssetListItemSerializer(serializers.Serializer):
    """One asset as the catalog browse list shows it.

    Every field is declared, unlike the map's asset detail: a list shows the
    same columns for every row, so a value the catalog does not hold is null
    rather than a missing key.
    """

    asset_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        read_only=True,
        help_text=(
            "Derived from the asset's source path, extension removed. The "
            "catalog has no name column (docs/adr/010)."
        ),
    )
    data_type = serializers.CharField(read_only=True)
    format = serializers.CharField(read_only=True, allow_null=True)
    topic_path = serializers.CharField(read_only=True, allow_null=True)
    bytes = serializers.IntegerField(read_only=True, allow_null=True)
    bbox = serializers.ListField(
        read_only=True,
        child=serializers.FloatField(),
        allow_null=True,
        min_length=4,
        max_length=4,
        help_text=(
            "The asset's coverage as [min_lon, min_lat, max_lon, max_lat], "
            "SRID 4326. Null when the asset has no coverage."
        ),
    )
    summary = serializers.CharField(read_only=True, allow_null=True)
    time_start = serializers.DateTimeField(read_only=True, allow_null=True)
    time_end = serializers.DateTimeField(read_only=True, allow_null=True)
    ingested_at = serializers.DateTimeField(read_only=True, allow_null=True)


class DataTypeCountSerializer(serializers.Serializer):
    """How many assets carry one data type.

    The data types come from the knowledge base; the portal neither defines nor
    translates the list (specs/map.md).
    """

    data_type = serializers.CharField(read_only=True)
    count = serializers.IntegerField(read_only=True)


class AssetListSerializer(serializers.Serializer):
    """One page of the catalog."""

    count = serializers.IntegerField(
        read_only=True, help_text="How many assets match, ignoring limit and offset."
    )
    results = AssetListItemSerializer(many=True, read_only=True)
    data_type_counts = DataTypeCountSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Counts per data type for the current filters, ignoring the data_type selection itself."
        ),
    )
