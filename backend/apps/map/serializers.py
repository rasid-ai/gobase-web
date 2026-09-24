from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.serializers import AreaField, BboxField

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


class AssetDataQuerySerializer(serializers.Serializer):
    """What a caller may ask for when reading an asset's features.

    `bbox` is a rectangle to read, and the map sends its padded viewport as
    one. `area` is a drawn polygon, read exactly, and replaces `bbox` rather
    than joining it — the two are two answers to "where", and sending both is
    refused rather than guessed at. `BboxField` and `AreaField` are the
    catalog's, so each means one thing across the API (docs/adr/011,
    docs/adr/014).
    """

    bbox = BboxField(
        required=False,
        help_text=(
            "Read only the features whose bounding box overlaps this area: "
            "min_lon,min_lat,max_lon,max_lat, SRID 4326. Matching is on "
            "bounding boxes, so a feature just outside the area may be "
            "included. Without it the whole file is in scope."
        ),
    )
    area = AreaField(
        required=False,
        help_text=(
            "Read only the features that intersect this drawn polygon: WKT, "
            "POLYGON((lon lat, ...)), SRID 4326, at most 100 corners and not "
            "crossing itself. Matching is exact. Sent instead of bbox."
        ),
    )
    cursor = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="The `next_cursor` of the previous page.",
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Features per page. Defaults to, and is capped at, the server's page size.",
    )

    def validate_limit(self, value):
        # Bounded against the setting rather than a literal so the ceiling is
        # configured in one place.
        return min(value, settings.LAKE_PAGE_SIZE)

    def validate(self, attrs):
        if "bbox" in attrs and "area" in attrs:
            raise serializers.ValidationError("Send a bbox or an area, not both.")
        return attrs


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
    next_cursor = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Pass back as `cursor` for the next page of this area. Null when this page is the last."
        ),
    )
    features = FeatureListField(
        read_only=True,
        child=serializers.JSONField(),
        help_text="GeoJSON Features, SRID 4326.",
    )
