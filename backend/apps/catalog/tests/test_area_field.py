"""`AreaField`: a drawn polygon, checked before PostGIS or DuckDB sees it.

The point of the checks is that neither engine refuses a bad polygon — a
self-intersecting one gets a silently wrong answer from both — so every shape
that would be invalid has to stop here. The cases below were each compared
with PostGIS's own `ST_IsValid` when the field was written.
"""

import pytest
from rest_framework.exceptions import ValidationError

from apps.catalog.serializers import MAX_AREA_VERTICES, Area, AreaField


def parse(text):
    return AreaField().run_validation(text)


def ring(corners: int) -> str:
    """A convex polygon with exactly `corners` corners: points on a circle."""
    import math

    points = [
        (
            round(math.cos(2 * math.pi * k / corners), 6),
            round(math.sin(2 * math.pi * k / corners), 6),
        )
        for k in range(corners)
    ]
    points.append(points[0])
    return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in points) + "))"


def test_a_simple_polygon_is_accepted_with_its_envelope():
    area = parse("POLYGON((35.47 33.86, 35.55 33.86, 35.58 33.92, 35.50 33.94, 35.47 33.86))")

    assert isinstance(area, Area)
    assert area.envelope == (35.47, 33.86, 35.58, 33.94)
    assert area.wkt.startswith("POLYGON((35.47 33.86, ")


def test_a_concave_polygon_is_accepted():
    """Concave is not invalid. An L-shape is a perfectly good area."""
    assert parse("POLYGON((0 0, 2 0, 2 1, 1 1, 1 2, 0 2, 0 0))")


def test_the_keyword_is_case_insensitive_and_spacing_is_forgiven():
    assert parse("  polygon (( 0 0 , 1 0,1 1 , 0 1, 0 0 ))  ")


def test_consecutive_repeated_points_are_dropped_not_refused():
    """A double click can land the same point twice; the shape is unchanged."""
    area = parse("POLYGON((0 0, 1 0, 1 0, 1 1, 0 1, 0 0))")
    assert area.wkt == "POLYGON((0.0 0.0, 1.0 0.0, 1.0 1.0, 0.0 1.0, 0.0 0.0))"


def test_the_corner_cap_is_inclusive():
    assert parse(ring(MAX_AREA_VERTICES))


@pytest.mark.parametrize(
    "text",
    [
        "POINT(0 0)",
        "LINESTRING(0 0, 1 1)",
        "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)))",
        "POLYGON((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 2 1, 2 2, 1 1))",
        "POLYGON((0 0, 1 0, 1 1, 0 0)",
        "POLYGON((0 0 0, 1 0 0, 1 1 0, 0 0 0))",
        "not a polygon",
        "",
    ],
    ids=[
        "point",
        "line",
        "multipolygon",
        "polygon with a hole",
        "unbalanced brackets",
        "three coordinates",
        "text",
        "empty",
    ],
)
def test_anything_but_one_ring_is_refused(text):
    with pytest.raises(ValidationError):
        parse(text)


@pytest.mark.parametrize(
    "text",
    [
        "POLYGON((0 0, 1 0, 1 1, 0 1, 0.5 0.5))",
        "POLYGON((0 0, 1 1, 0 0))",
        "POLYGON((0 0, 1 1, 2 2, 0 0))",
        "POLYGON((0 0, nan 0, 1 1, 0 0))",
        "POLYGON((0 0, inf 0, 1 1, 0 0))",
        "POLYGON((0 0, 181 0, 1 1, 0 0))",
        "POLYGON((0 0, 1 91, 1 1, 0 0))",
    ],
    ids=["unclosed", "too few corners", "flat", "nan", "infinite", "longitude", "latitude"],
)
def test_malformed_rings_are_refused(text):
    with pytest.raises(ValidationError):
        parse(text)


def test_one_corner_over_the_cap_is_refused():
    """The cap exists because gunicorn refuses a request line over 4094 bytes."""
    with pytest.raises(ValidationError) as caught:
        parse(ring(MAX_AREA_VERTICES + 1))
    assert "at most" in str(caught.value.detail)


@pytest.mark.parametrize(
    "text",
    [
        "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))",
        "POLYGON((0 0, 2 0, 1 0, 1 1, 0 0))",
        "POLYGON((0 0, 1 0, -1 0, 0 1, 0 0))",
        "POLYGON((0 0, 2 0, 2 2, 1 0, 0 2, 0 0))",
    ],
    ids=["bowtie", "spike doubling back", "spike past the start", "touching itself"],
)
def test_a_polygon_that_crosses_or_touches_itself_is_refused(text):
    """Both engines answer these silently and wrongly, so this is the only guard."""
    with pytest.raises(ValidationError) as caught:
        parse(text)
    assert "crosses or touches itself" in str(caught.value.detail)
