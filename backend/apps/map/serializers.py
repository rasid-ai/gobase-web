from rest_framework import serializers


class AssetSummarySerializer(serializers.Serializer):
    """One asset as it appears in a point-click list."""

    asset_id = serializers.UUIDField(read_only=True)
    source_uri = serializers.CharField(read_only=True)
    format = serializers.CharField(read_only=True, allow_null=True)
    summary = serializers.CharField(read_only=True, allow_null=True)
    time_start = serializers.DateTimeField(read_only=True, allow_null=True)
    time_end = serializers.DateTimeField(read_only=True, allow_null=True)


class AssetGroupSerializer(serializers.Serializer):
    """Assets sharing a data type.

    The data type is whatever the knowledge base classifies the asset as; the
    portal neither defines nor translates the list (specs/map.md).
    """

    data_type = serializers.CharField(read_only=True)
    assets = AssetSummarySerializer(many=True, read_only=True)


class AssetsAtPointSerializer(serializers.Serializer):
    """The whole answer to a point click. No coverage means no groups."""

    groups = AssetGroupSerializer(many=True, read_only=True)


class AssetDetailSerializer(serializers.Serializer):
    """One asset's dynamic metadata and its footprint."""

    asset_id = serializers.UUIDField(read_only=True)
    data_type = serializers.CharField(read_only=True)
    metadata = serializers.DictField(
        read_only=True,
        help_text=(
            "Whatever the catalog holds for this asset. The key set is not "
            "fixed and differs by data type."
        ),
    )
    footprint = serializers.JSONField(
        read_only=True,
        help_text="The asset's coverage as a GeoJSON geometry, SRID 4326.",
    )
