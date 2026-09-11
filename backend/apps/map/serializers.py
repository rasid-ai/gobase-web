from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

# A GeoJSON Feature as the contract describes it (RFC 7946). `geometry` stays a
# free-form object because GeoJSON allows seven geometry types and a null, and
# `properties` stays open because they are whatever columns the file holds.
# Without this the contract says `items: {}` and the generated client types the
# features as `unknown[]`.
GEOJSON_FEATURE = {
    "type": "object",
    "title": "Feature",
    "properties": {
        "type": {"type": "string", "enum": ["Feature"]},
        "geometry": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
            "description": "A GeoJSON geometry, SRID 4326.",
        },
        "properties": {
            "type": "object",
            "additionalProperties": True,
            "description": "The file's non-geometry columns.",
        },
    },
    "required": ["type", "geometry", "properties"],
}


@extend_schema_field({"type": "array", "items": GEOJSON_FEATURE})
class FeatureListField(serializers.ListField):
    """A list of GeoJSON Features, typed in the contract but not validated here.

    The server builds these itself from the lake, so there is nothing to
    validate on the way in; the annotation exists for the generated client.
    """


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


class AssetDataSerializer(serializers.Serializer):
    """A vector asset's features, read from the lake.

    There is no serializer for a feature: its properties are whatever columns
    the GeoParquet file holds, and they differ per file. The shape is declared
    to the contract instead, by `FeatureListField`, so the generated client
    still gets a typed array rather than `unknown[]`.
    """

    asset_id = serializers.UUIDField(read_only=True)
    count = serializers.IntegerField(
        read_only=True, help_text="How many features are in this response."
    )
    truncated = serializers.BooleanField(
        read_only=True,
        help_text="True when the file held more features than the server returns.",
    )
    features = FeatureListField(
        read_only=True,
        child=serializers.JSONField(),
        help_text="GeoJSON Features, SRID 4326.",
    )
