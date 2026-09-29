from rest_framework import serializers


class PlaceSearchQuerySerializer(serializers.Serializer):
    """The search text, validated before anything reaches the geocoder."""

    q = serializers.CharField(
        min_length=1,
        max_length=200,
        trim_whitespace=True,
        help_text="A place name or address, as one line.",
    )


class PlaceSerializer(serializers.Serializer):
    """One candidate place. Nothing here names a vendor."""

    name = serializers.CharField(
        read_only=True,
        help_text="The place as a single line, for example 'Beirut, Lebanon'.",
    )
    lat = serializers.FloatField(read_only=True)
    lon = serializers.FloatField(read_only=True)
    bbox = serializers.ListField(
        read_only=True,
        child=serializers.FloatField(),
        allow_null=True,
        min_length=4,
        max_length=4,
        help_text=(
            "The place's extent as [min_lon, min_lat, max_lon, max_lat], SRID "
            "4326 — the same shape as an asset's bbox, so the two can be "
            "compared without reordering. Null when the geocoder returned no "
            "extent, or one that crosses the antimeridian."
        ),
    )


class PlaceSearchSerializer(serializers.Serializer):
    """Every candidate for one search, best first."""

    results = PlaceSerializer(many=True, read_only=True)
