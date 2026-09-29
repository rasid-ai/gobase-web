"""Fixtures for the Map tests.

`kb` is mirrored onto `default` in tests (context/integrations/kb.md), so no
real knowledge base exists here. Catalog reads are faked at the catalog
boundary; the lake is exercised for real against a GeoParquet file written to a
temporary directory, which DuckDB reads from a local path exactly as it reads
one from S3.
"""

import duckdb
import pytest
from django.contrib.auth.models import User

from apps.accounts.models import Role, UserProfile
from apps.map import lake

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def as_viewer(api, db):
    user = User.objects.create_user(username="map-viewer", password=PASSWORD)
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    response = api.post(
        "/api/auth/login", {"username": "map-viewer", "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api


@pytest.fixture(autouse=True)
def _fresh_lake_connection():
    """Rebuild the shared connection around every test.

    The connection is per process and carries its S3 configuration, so a test
    that changes settings would otherwise leak into the next one.
    """
    lake.reset()
    yield
    lake.reset()


def write_geoparquet(path, rows: int = 3, mixed: bool = True) -> str:
    """Write a small GeoParquet file and return its path.

    Mixed geometry on purpose: 10 of the 22 real layers are `Mixed`
    (context/integrations/kb.md), so points, lines and polygons in one file is
    the normal case rather than an edge case.
    """
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")

    if mixed:
        geometries = [
            "ST_Point(13.73, 51.05)",
            "ST_GeomFromText('LINESTRING(13.7 51.0, 13.8 51.1)')",
            "ST_GeomFromText('POLYGON((13.7 51.0, 13.8 51.0, 13.8 51.1, 13.7 51.1, 13.7 51.0))')",
        ]
    else:
        geometries = ["ST_Point(13.73, 51.05)"]

    values = ",".join(
        f"({index}, 'feature-{index}', {geometries[index % len(geometries)]})"
        for index in range(rows)
    )
    connection.execute(
        f"COPY (SELECT * FROM (VALUES {values}) AS t(osm_id, name, geometry)) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()
    return str(path)


def write_covered_points(path, rows: int, row_group_size: int = 25) -> str:
    """The same spread points, written the way silver writes them.

    A `bbox` STRUCT covering column, one box per feature, plus small row groups
    — which is what makes the covering column worth anything, since DuckDB
    prunes by row-group statistics. Written by DuckDB's own COPY, so the `geo`
    metadata carries no `covering` key: that is exactly why the reader detects
    the column by name and type instead.
    """
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")
    connection.execute(
        f"COPY (SELECT ST_Point(i * 1.0, 0.0) AS geometry, i AS osm_id, "
        f"'feature-' || i AS name, "
        f"{{'xmin': i * 1.0, 'ymin': 0.0, 'xmax': i * 1.0, 'ymax': 0.0}} AS bbox "
        f"FROM range(0, {int(rows)}) t(i)) "
        f"TO '{path}' (FORMAT PARQUET, ROW_GROUP_SIZE {int(row_group_size)})"
    )
    connection.close()
    return str(path)


def write_spread_points(path, rows: int) -> str:
    """Write a GeoParquet file of points one degree apart along the equator.

    `write_geoparquet` puts every feature in one small area, which is what a
    shape test wants and no use at all to an area test. Here `osm_id` is also
    the longitude, so a bbox picks out a range of ids that is obvious to read
    in an assertion.
    """
    connection = duckdb.connect(":memory:")
    connection.execute("INSTALL spatial; LOAD spatial;")
    connection.execute(
        f"COPY (SELECT i AS osm_id, 'feature-' || i AS name, "
        f"ST_Point(i * 1.0, 0.0) AS geometry FROM range(0, {int(rows)}) t(i)) "
        f"TO '{path}' (FORMAT PARQUET)"
    )
    connection.close()
    return str(path)
