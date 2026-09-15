from rest_framework import serializers

from .kb import SORTS


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
