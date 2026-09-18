import math

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
