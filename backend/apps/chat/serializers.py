"""The chat contract: what the SPA sends, and what the agent's answers may hold.

The answer side does two jobs. It is the schema in `openapi.yaml`, which the
SPA's types are generated from, and it is the check on what the agent sent:
the relay passes an event on only after it fits one of these shapes, so the
SPA never receives a field the contract does not name (docs/adr/023).
context/integrations/agent.md maps each one onto the agent's own.

Text fields that carry the answer keep their whitespace. DRF trims a
CharField by default, and a streamed piece like " and" would lose its space.
"""

import math

from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from apps.catalog.serializers import AreaField, BboxField

# The longest question accepted, in characters. A question is a sentence or a
# paragraph; this only stops a pasted document reaching the model.
MAX_PROMPT_CHARS = 4000

REFERENCE_KINDS = ["asset", "layer", "passage", "raster", "frame"]
FILTER_OPERATORS = ["equals", "contains", "in", "<", ">"]
STEP_STATUSES = ["started", "finished", "failed"]


# --- what the SPA sends -----------------------------------------------------


class AskContextSerializer(serializers.Serializer):
    """The map's state when the question was asked, as data rather than prose.

    Every field is optional. The agent reads it as what "here" means: the
    model picks a scope by name and the agent's tools take the geometry from
    here, so the model never copies coordinates (docs/adr/023).
    """

    viewport = serializers.ListField(
        child=serializers.FloatField(),
        min_length=4,
        max_length=4,
        required=False,
        help_text="What the map shows: [min_lon, min_lat, max_lon, max_lat], SRID 4326.",
    )
    point = serializers.ListField(
        child=serializers.FloatField(),
        min_length=2,
        max_length=2,
        required=False,
        help_text="A clicked point: [lon, lat], SRID 4326.",
    )
    area = AreaField(
        required=False,
        help_text=(
            "A drawn polygon as WKT, POLYGON((lon lat, lon lat, ...)), SRID 4326. "
            "Checked as the catalog checks it: one ring, closed, never crossing itself."
        ),
    )
    asset_id = serializers.UUIDField(
        required=False, help_text="The asset selected in the map's panel."
    )

    def validate_viewport(self, value):
        # The catalog's own check, so a viewport here is a bbox anywhere else.
        return BboxField().run_validation(",".join(repr(corner) for corner in value))

    def validate_point(self, value):
        lon, lat = value
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise serializers.ValidationError("point must be two finite numbers.")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise serializers.ValidationError(
                "Longitudes must be between -180 and 180, latitudes between -90 and 90."
            )
        return value


def agent_context(data: dict) -> dict:
    """A validated context in the agent's terms, with absent fields left out."""
    context = {}
    if "viewport" in data:
        context["viewport"] = data["viewport"]
    if "point" in data:
        context["point"] = data["point"]
    if "area" in data:
        context["area"] = data["area"].wkt
    if "asset_id" in data:
        context["asset_id"] = str(data["asset_id"])
    return context


class AskTurnRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=MAX_PROMPT_CHARS, help_text="The question, in any language."
    )
    context = AskContextSerializer(required=False)


# --- what an answer holds ---------------------------------------------------


class ChatFilterSerializer(serializers.Serializer):
    """A simple attribute filter: one column, one operator, one value (docs/adr/024).

    Not free SQL and not group-by. The backend binds the value as a parameter
    wherever it applies one.
    """

    column = serializers.CharField(help_text="A column the asset has.")
    op = serializers.ChoiceField(choices=FILTER_OPERATORS)
    value = serializers.JSONField(help_text="A string or a number; a list of them for `in`.")


class ChatReferenceSerializer(serializers.Serializer):
    """Something an answer points to besides its text.

    It carries only what the SPA needs to show it through this backend's
    existing endpoints — never features, pixels or PDF bytes (docs/adr/024).
    Which fields are set depends on `kind`:

    - `asset`: `asset_id` — an asset the answer names.
    - `layer`: `asset_id`, `area` or `bbox`, `filter`, `total` — vector
      features to draw from `/api/map/assets/{id}/data`.
    - `passage`: `asset_id`, `chunk_id`, `page` — a passage of a document.
    - `raster`: `asset_id`, `area` or `bbox`, `stats` — figures read from a
      raster over an area.
    - `frame`: `bbox` — where the map should look.
    """

    kind = serializers.ChoiceField(choices=REFERENCE_KINDS)
    asset_id = serializers.UUIDField(required=False, help_text="Every kind but `frame`.")
    area = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="The polygon it was read for, as WKT, when it was a drawn area.",
    )
    bbox = serializers.ListField(
        child=serializers.FloatField(),
        min_length=4,
        max_length=4,
        required=False,
        allow_null=True,
        help_text="[min_lon, min_lat, max_lon, max_lat], SRID 4326.",
    )
    filter = ChatFilterSerializer(required=False, allow_null=True)
    total = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="A layer's exact feature count inside its area, filter applied.",
    )
    chunk_id = serializers.CharField(required=False, help_text="A passage's id in the chunk index.")
    page = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="A passage's first page, counted from 1.",
    )
    stats = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="A raster's figures as the answer used them: per band, or per class.",
    )

    def validate(self, attrs):
        kind = attrs["kind"]
        if kind == "frame":
            if not attrs.get("bbox"):
                raise serializers.ValidationError("A frame needs a bbox.")
        elif "asset_id" not in attrs:
            raise serializers.ValidationError(f"A {kind} reference needs an asset_id.")
        if kind == "passage" and not attrs.get("chunk_id"):
            raise serializers.ValidationError("A passage needs a chunk_id.")
        return attrs

    def to_representation(self, instance):
        # Only the fields this kind has. DRF writes every nullable field it
        # was not given as null, which would make a passage look like it has
        # an empty area and filter.
        return {
            key: value
            for key, value in super().to_representation(instance).items()
            if value is not None
        }


def _event(name: str) -> serializers.ChoiceField:
    return serializers.ChoiceField(choices=[name], help_text="What this event is.")


class ChatTextEventSerializer(serializers.Serializer):
    """A piece of the answer's text, to append to what came before."""

    event = _event("text")
    delta = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ChatStepEventSerializer(serializers.Serializer):
    """The agent started or finished looking something up. Holds no data."""

    event = _event("step")
    tool = serializers.CharField()
    status = serializers.ChoiceField(choices=STEP_STATUSES)
    note = serializers.CharField(required=False, allow_blank=True)


class ChatReferenceEventSerializer(serializers.Serializer):
    """Something the answer points to, as soon as a lookup found it."""

    event = _event("reference")
    reference = ChatReferenceSerializer()


class ChatDoneEventSerializer(serializers.Serializer):
    """The whole answer, checked by the agent. The last event of a whole answer."""

    event = _event("done")
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)
    references = ChatReferenceSerializer(many=True)


class ChatErrorEventSerializer(serializers.Serializer):
    """The answer stopped part-way. The last event of an incomplete answer.

    What streamed before it stays on screen, marked incomplete; it is never
    shown as a whole answer. The session stays usable for the next question.
    """

    event = _event("error")
    message = serializers.CharField()
    incomplete = serializers.BooleanField()


EVENT_SERIALIZERS = {
    "text": ChatTextEventSerializer,
    "step": ChatStepEventSerializer,
    "reference": ChatReferenceEventSerializer,
    "done": ChatDoneEventSerializer,
    "error": ChatErrorEventSerializer,
}

# The stream's schema in openapi.yaml: one of the five, told apart by `event`.
ChatTurnEventSchema = PolymorphicProxySerializer(
    component_name="ChatTurnEvent",
    serializers=EVENT_SERIALIZERS,
    resource_type_field_name="event",
    many=False,
)


# --- sessions ---------------------------------------------------------------


class ChatSessionSerializer(serializers.Serializer):
    """One session, as the session list shows it."""

    session_id = serializers.UUIDField()
    title = serializers.CharField(
        allow_blank=True, help_text="The session's first question, as the agent stored it."
    )
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class ChatSessionListSerializer(serializers.Serializer):
    """The signed-in user's sessions, newest first."""

    results = ChatSessionSerializer(many=True)


class ChatTurnSerializer(serializers.Serializer):
    """One question and its answer, as the session stored them."""

    prompt = serializers.CharField(trim_whitespace=False)
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)
    references = ChatReferenceSerializer(many=True)
    incomplete = serializers.BooleanField(
        default=False, help_text="True when the answer stopped part-way."
    )


class ChatSessionDetailSerializer(ChatSessionSerializer):
    """One session with every turn, oldest first."""

    turns = ChatTurnSerializer(many=True)
