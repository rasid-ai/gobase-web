"""GET /api/map/assets/{id}/data — the endpoint around the lake reader.

The catalog is faked at its own boundary because tests have no real `kb`
(context/integrations/kb.md). The lake is not faked: the endpoint reads a real
GeoParquet file, so the response shape is checked against actual output.
"""

import uuid

import pytest

from apps.catalog import kb
from apps.map import lake

from .conftest import write_geoparquet

ASSET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def url(asset_id=ASSET_ID) -> str:
    return f"/api/map/assets/{asset_id}/data"


def test_requires_authentication(api):
    assert api.get(url()).status_code == 401


def test_returns_features_for_a_vector_asset(as_viewer, monkeypatch, tmp_path):
    path = write_geoparquet(tmp_path / "asset.parquet", rows=3)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    response = as_viewer.get(url())

    assert response.status_code == 200
    body = response.json()
    assert body["asset_id"] == str(ASSET_ID)
    assert body["count"] == 3
    assert body["truncated"] is False
    assert len(body["features"]) == 3
    assert body["features"][0]["type"] == "Feature"
    assert body["features"][0]["geometry"]["type"] in {"Point", "LineString", "Polygon"}


def test_caps_features_and_reports_truncation(as_viewer, monkeypatch, tmp_path, settings):
    path = write_geoparquet(tmp_path / "big.parquet", rows=30)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)
    settings.LAKE_MAX_FEATURES = 5

    response = as_viewer.get(url())

    assert response.status_code == 200
    assert response.json()["count"] == 5
    assert response.json()["truncated"] is True


@pytest.mark.parametrize(
    "reason",
    ["no such id", "superseded or failed", "another modality"],
    ids=["unknown", "inactive", "raster"],
)
def test_anything_the_catalog_does_not_return_is_404(as_viewer, monkeypatch, reason):
    """All three misses are one answer: the portal does not tell them apart."""
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: None)

    assert as_viewer.get(url()).status_code == 404


def test_an_unreachable_lake_is_503(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: "s3://b/x.parquet")

    def unavailable(uri, limit):
        raise lake.LakeUnavailable("connection refused")

    monkeypatch.setattr(lake, "read_vector_asset", unavailable)

    assert as_viewer.get(url()).status_code == 503


def test_an_unreadable_file_is_502(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: "s3://b/x.parquet")

    def unreadable(uri, limit):
        raise lake.LakeReadError("not a parquet file")

    monkeypatch.setattr(lake, "read_vector_asset", unreadable)

    assert as_viewer.get(url()).status_code == 502


def test_the_lake_path_never_reaches_the_client(as_viewer, monkeypatch, tmp_path):
    """`source_uri` is a location in the bucket and stays on the server."""
    path = write_geoparquet(tmp_path / "secret-bucket-path.parquet", rows=1)
    monkeypatch.setattr(kb, "vector_source_uri", lambda asset_id: path)

    body = as_viewer.get(url()).content.decode()

    assert "secret-bucket-path" not in body


def test_a_malformed_uuid_is_404_not_500(as_viewer):
    assert as_viewer.get("/api/map/assets/not-a-uuid/data").status_code == 404
