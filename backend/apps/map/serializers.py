from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.serializers import AreaField, BboxField

from . import lake

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


class AssetDetailSerializer(serializers.Serializer):
    """One asset's dynamic metadata and its footprint."""

    asset_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        read_only=True,
        help_text=(
            "Derived from the asset's source path, extension removed — the same "
            "name the catalog list shows (docs/adr/010)."
        ),
    )
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


class AttributeFilterQuerySerializer(serializers.Serializer):
    """A simple attribute filter: one column, one operator, a value (docs/adr/028).

    Three parameters, sent together or not at all. Not SQL: the column must be
    one the file has, the operator is from a fixed list, and the value is
    bound as a parameter. Whether the column exists, and whether the value
    fits its type, is only known once the file is read, so the reader checks
    those and the view answers 400 the same way.
    """

    filter_column = serializers.CharField(
        required=False,
        max_length=255,
        trim_whitespace=False,
        help_text=(
            "Keep only the features whose value in this column matches. A column "
            "of the asset, as its metadata lists them. Sent with filter_op and "
            "filter_value."
        ),
    )
    filter_op = serializers.ChoiceField(
        required=False,
        choices=lake.FILTER_OPERATORS,
        help_text=(
            "How to compare. `equals` and `in`: text without regard to case, other "
            "types by value. `contains`: text columns only, without regard to case. "
            "`<` and `>`: numbers, dates and timestamps only. A null never matches."
        ),
    )
    filter_value = serializers.ListField(
        required=False,
        child=serializers.CharField(
            allow_blank=True, trim_whitespace=False, max_length=lake.MAX_FILTER_VALUE_CHARS
        ),
        max_length=lake.MAX_FILTER_VALUES,
        help_text=(
            "The value to compare with, as text. Repeat the parameter to give `in` "
            f"several, up to {lake.MAX_FILTER_VALUES}; every other operator takes one."
        ),
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        sent = [name for name in ("filter_column", "filter_op", "filter_value") if name in attrs]
        if sent and len(sent) < 3:
            raise serializers.ValidationError(
                "A filter needs filter_column, filter_op and filter_value together."
            )
        if sent:
            values = attrs["filter_value"]
            if not values:
                raise serializers.ValidationError({"filter_value": "A filter needs a value."})
            if attrs["filter_op"] != "in" and len(values) != 1:
                raise serializers.ValidationError(
                    {
                        "filter_value": (
                            f"`{attrs['filter_op']}` takes one value; use `in` for several."
                        )
                    }
                )
        return attrs

    def attribute_filter(self) -> lake.AttributeFilter | None:
        """The validated filter in the reader's terms, or None when none was sent."""
        asked = self.validated_data
        if "filter_column" not in asked:
            return None
        return lake.AttributeFilter(
            column=asked["filter_column"],
            op=asked["filter_op"],
            values=tuple(asked["filter_value"]),
        )


class AssetDataQuerySerializer(AttributeFilterQuerySerializer):
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
        attrs = super().validate(attrs)
        if "bbox" in attrs and "area" in attrs:
            raise serializers.ValidationError("Send a bbox or an area, not both.")
        return attrs


# The most sample rows a summary returns. A summary is for an answer, which
# quotes a few rows; the features themselves come from /data.
MAX_SUMMARY_SAMPLE = 10


class AssetSummaryQuerySerializer(AttributeFilterQuerySerializer):
    """What a caller may ask for when counting an asset's features.

    The same place and the same filter as `/data` takes (docs/adr/028).
    Matching is always exact here, for a bbox too. `/data` tests a bbox by
    bounding boxes, so a layer drawn for a count shows the same features only
    when both are sent the place as an `area`.
    """

    bbox = BboxField(
        required=False,
        help_text=(
            "Count only the features that intersect this rectangle: "
            "min_lon,min_lat,max_lon,max_lat, SRID 4326. Exact: a feature whose "
            "bounding box overlaps it but whose shape does not is left out. "
            "Without bbox or area the whole file is counted."
        ),
    )
    area = AreaField(
        required=False,
        help_text=(
            "Count only the features that intersect this drawn polygon: WKT, "
            "POLYGON((lon lat, ...)), SRID 4326, at most 100 corners and not "
            "crossing itself. Sent instead of bbox."
        ),
    )
    sample = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=MAX_SUMMARY_SAMPLE,
        default=5,
        help_text="How many matching rows to return as a sample, in file order.",
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if "bbox" in attrs and "area" in attrs:
            raise serializers.ValidationError("Send a bbox or an area, not both.")
        return attrs


class AssetSummarySerializer(serializers.Serializer):
    """How many of a vector asset's features match, and what a few of them hold.

    What the Ask agent's `vector_features` tool reads (docs/adr/024,
    docs/adr/028). Small on purpose: a count and a few rows of properties, no
    geometry. The features themselves are drawn from `/data` with the same
    place and filter.
    """

    asset_id = serializers.UUIDField(read_only=True)
    total = serializers.IntegerField(
        read_only=True,
        help_text="The exact number of features inside the place, filter applied.",
    )
    sample = serializers.ListField(
        read_only=True,
        child=serializers.DictField(),
        help_text=(
            "The properties of the first matching features in file order: the "
            "file's non-geometry columns, as `/data` writes them."
        ),
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


class LakeCredentialsSerializer(serializers.Serializer):
    """Temporary S3 credentials: the three values a client signs with, and when they stop."""

    access_key_id = serializers.CharField(read_only=True)
    secret_access_key = serializers.CharField(read_only=True)
    session_token = serializers.CharField(
        read_only=True,
        help_text="Sent with every request, as the x-amz-security-token header, and signed.",
    )
    expires_at = serializers.DateTimeField(
        read_only=True,
        help_text="After this the lake refuses them. Ask again before then.",
    )


class RasterAccessSerializer(serializers.Serializer):
    """Where one raster is in the lake, and credentials that can read it.

    For a desktop client that reads the COG itself, with range requests it
    signs (docs/adr/022). The credentials read this one object and list the
    names in its folder; nothing else.
    """

    asset_id = serializers.UUIDField(read_only=True)
    url = serializers.CharField(
        read_only=True,
        help_text=(
            "The COG's address on the lake, path-style: endpoint, bucket, key. "
            "Reading it takes the credentials; it is not a presigned link."
        ),
    )
    endpoint = serializers.CharField(
        read_only=True,
        help_text="The lake as a desktop client reaches it: scheme, host and port.",
    )
    region = serializers.CharField(
        read_only=True, help_text="The region to sign for. The lake has no others."
    )
    bucket = serializers.CharField(read_only=True)
    key = serializers.CharField(read_only=True, help_text="The object's key inside the bucket.")
    credentials = LakeCredentialsSerializer(read_only=True)


class RasterPlaceQuerySerializer(serializers.Serializer):
    """Where on a raster a caller is asking about.

    The same two shapes every place takes across the API: a rectangle or a
    drawn polygon, SRID 4326, never both (docs/adr/011, docs/adr/014).
    """

    bbox = BboxField(
        required=False,
        help_text=(
            "A rectangle: min_lon,min_lat,max_lon,max_lat, SRID 4326. For "
            "raster-stats, only the pixels whose centre is inside it are "
            "counted, and without bbox or area the whole raster is. For "
            "clip.tif, the pixels over it are returned."
        ),
    )
    area = AreaField(
        required=False,
        help_text=(
            "A drawn polygon: WKT, POLYGON((lon lat, ...)), SRID 4326, at most "
            "100 corners and not crossing itself. Sent instead of bbox. For "
            "raster-stats, only the pixels whose centre is inside it are "
            "counted. For clip.tif, the pixels over its envelope are returned: "
            "a clip is a rectangle, never a polygon mask."
        ),
    )

    def validate(self, attrs):
        if "bbox" in attrs and "area" in attrs:
            raise serializers.ValidationError("Send a bbox or an area, not both.")
        return attrs


class RasterClipQuerySerializer(RasterPlaceQuerySerializer):
    """A clip needs a place: the whole raster is what raster-access is for."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if "bbox" not in attrs and "area" not in attrs:
            raise serializers.ValidationError("Send a bbox or an area to clip to.")
        return attrs


class RasterBandStatsSerializer(serializers.Serializer):
    """One band's figures over the pixels that hold data inside the place."""

    index = serializers.IntegerField(read_only=True, help_text="The band's number, from 1.")
    min = serializers.FloatField(
        read_only=True, allow_null=True, help_text="Null when no pixel holds data."
    )
    max = serializers.FloatField(read_only=True, allow_null=True)
    mean = serializers.FloatField(read_only=True, allow_null=True)
    valid_percent = serializers.FloatField(
        read_only=True,
        help_text="The share of the place's pixels that hold data (not nodata), 0 to 100.",
    )


class RasterClassSerializer(serializers.Serializer):
    """One class of a classified raster, inside the place."""

    value = serializers.IntegerField(read_only=True, help_text="The pixel value.")
    name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="The class's name from the raster's legend. Null when the legend has none.",
    )
    pixels = serializers.IntegerField(read_only=True)
    share = serializers.FloatField(
        read_only=True,
        help_text="This class's part of the pixels that hold data, 0 to 1.",
    )


class RasterOtherClassesSerializer(serializers.Serializer):
    """The classes left out of the list, as one sum."""

    values = serializers.IntegerField(read_only=True, help_text="How many values were left out.")
    pixels = serializers.IntegerField(read_only=True)
    share = serializers.FloatField(
        read_only=True, help_text="Their part of the pixels that hold data, 0 to 1."
    )


class RasterStatsSerializer(serializers.Serializer):
    """What a raster's pixels say inside a place.

    What the Ask agent's `raster_clip` tool reads (docs/adr/024,
    docs/adr/029). Small on purpose: figures, never pixels. The pixels are a
    separate download, `clip.tif`.
    """

    asset_id = serializers.UUIDField(read_only=True)
    pixels = serializers.IntegerField(
        read_only=True,
        help_text=(
            "How many pixels are inside the place, on the grid that was read. "
            "0 when the place misses the raster; there are then no figures."
        ),
    )
    approximate = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when the place holds more pixels than the server reads at "
            "once: it was then read at reduced size, so `pixels` counts that "
            "smaller grid and the figures and shares are close, not exact."
        ),
    )
    bands = RasterBandStatsSerializer(read_only=True, many=True)
    classes = RasterClassSerializer(
        read_only=True,
        many=True,
        allow_null=True,
        help_text=(
            "For a classified raster (one whole-number band with a legend in "
            "its tags): the values found, largest share first, at most 256. "
            "Null for any other raster."
        ),
    )
    other_classes = RasterOtherClassesSerializer(
        read_only=True,
        allow_null=True,
        help_text=(
            "Every value beyond those in `classes`, summed, so the shares add "
            "up to 1. Null when `classes` holds them all, and for a raster "
            "that is not classified."
        ),
    )
