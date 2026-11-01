"""GET /api/map/assets/{id}/raster-access — lake credentials for one raster.

The catalog is faked at its own boundary, as for `/data`. The lake's STS is
faked with botocore's Stubber, which checks each request against the real
AssumeRole model, so a wrong parameter name or type fails here and not on the
VPS. The live call was checked by hand against RustFS (docs/adr/022).
"""

import json
import logging
import uuid
from datetime import UTC, datetime

import pytest
from botocore.stub import ANY, Stubber
from django.contrib.auth.models import User

from apps.accounts.models import ApiKey, Role, UserProfile
from apps.catalog import kb
from apps.map import sts

ASSET_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
SOURCE_URI = "s3://geobase-silver/raster/esri_landcover/lulc_2021.tif"
EXPIRES = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)

# Placeholders in the shape STS answers with, not real credentials.
TEMPORARY = {
    "AccessKeyId": "TEMPORARYKEYID000000",
    "SecretAccessKey": "temporary-secret-placeholder",
    "SessionToken": "temporary.session.token",
    "Expiration": EXPIRES,
}


def url(asset_id=ASSET_ID) -> str:
    return f"/api/map/assets/{asset_id}/raster-access"


@pytest.fixture(autouse=True)
def lake_sts(settings):
    """A portal set up for raster access, with a fresh STS client per test."""
    settings.LAKE_PUBLIC_ENDPOINT = "https://lake.portal.test/"
    settings.LAKE_S3_ENDPOINT = "127.0.0.1:9000"
    settings.LAKE_S3_USE_SSL = False
    settings.LAKE_S3_REGION = ""
    settings.LAKE_STS_ACCESS_KEY = "portal-raster-issuer"
    settings.LAKE_STS_SECRET_KEY = "issuer-password-placeholder"
    settings.LAKE_STS_DURATION_SECONDS = 3600
    sts.reset()
    yield settings
    sts.reset()


@pytest.fixture
def a_raster(monkeypatch):
    monkeypatch.setattr(kb, "raster_source_uri", lambda asset_id: SOURCE_URI)


@pytest.fixture
def stub():
    with Stubber(sts._sts_client()) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


def expect_assume_role(stub, **expected):
    params = {
        "RoleArn": ANY,
        "RoleSessionName": ANY,
        "DurationSeconds": ANY,
        "Policy": ANY,
    }
    params.update(expected)
    stub.add_response("assume_role", {"Credentials": TEMPORARY}, params)


# --- the answer -----------------------------------------------------------


def test_requires_authentication(api):
    assert api.get(url()).status_code == 401


def test_returns_the_address_and_the_credentials(as_viewer, a_raster, stub):
    expect_assume_role(stub)

    response = as_viewer.get(url())

    assert response.status_code == 200
    assert response.json() == {
        "asset_id": str(ASSET_ID),
        "url": "https://lake.portal.test/geobase-silver/raster/esri_landcover/lulc_2021.tif",
        "endpoint": "https://lake.portal.test",
        "region": "us-east-1",
        "bucket": "geobase-silver",
        "key": "raster/esri_landcover/lulc_2021.tif",
        "credentials": {
            "access_key_id": "TEMPORARYKEYID000000",
            "secret_access_key": "temporary-secret-placeholder",
            "session_token": "temporary.session.token",
            "expires_at": "2026-11-01T18:00:00Z",
        },
    }


def test_no_cache_may_keep_the_answer(as_viewer, a_raster, stub):
    expect_assume_role(stub)

    assert as_viewer.get(url())["Cache-Control"] == "no-store"


def test_the_configured_region_is_the_one_signed_for(as_viewer, a_raster, lake_sts):
    lake_sts.LAKE_S3_REGION = "eu-central-1"
    sts.reset()
    with Stubber(sts._sts_client()) as stubber:
        expect_assume_role(stubber)
        assert as_viewer.get(url()).json()["region"] == "eu-central-1"


def test_an_api_key_may_ask(api, db, a_raster, stub):
    """The add-in signs in with a key, and a key may only GET (docs/adr/021)."""
    user = User.objects.create_user(username="desktop", password="unused-password-1")
    UserProfile.objects.create(user=user, role=Role.VIEWER)
    _, raw = ApiKey.issue(user, "ArcGIS Pro on DESKTOP-1")
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    expect_assume_role(stub)

    assert api.get(url()).status_code == 200


# --- what is asked of the lake ---------------------------------------------


def test_the_session_is_named_after_the_user(as_viewer, a_raster, stub):
    user = User.objects.get(username="map-viewer")
    expect_assume_role(stub, RoleSessionName=f"portal-user-{user.pk}")

    assert as_viewer.get(url()).status_code == 200


def test_the_credentials_last_the_configured_time(as_viewer, a_raster, stub, lake_sts):
    lake_sts.LAKE_STS_DURATION_SECONDS = 7200
    expect_assume_role(stub, DurationSeconds=7200)

    assert as_viewer.get(url()).status_code == 200


@pytest.mark.parametrize(("configured", "sent"), [(60, 900), (100_000, 43200)])
def test_the_duration_stays_inside_what_sts_allows(lake_sts, configured, sent):
    lake_sts.LAKE_STS_DURATION_SECONDS = configured

    assert sts.duration_seconds() == sent


def test_the_session_policy_reads_one_object_and_lists_its_folder():
    policy = json.loads(sts.session_policy("geobase-silver", "raster/esri/lulc_2021.tif"))

    read, listing = policy["Statement"]
    assert read["Action"] == ["s3:GetObject"]
    assert read["Resource"] == ["arn:aws:s3:::geobase-silver/raster/esri/lulc_2021.tif"]
    assert listing["Action"] == ["s3:ListBucket"]
    assert listing["Resource"] == ["arn:aws:s3:::geobase-silver"]
    assert listing["Condition"] == {"StringLike": {"s3:prefix": ["raster/esri/*"]}}
    assert all(statement["Effect"] == "Allow" for statement in policy["Statement"])


def test_a_session_policy_over_the_limit_is_refused():
    with pytest.raises(ValueError):
        sts.session_policy("geobase-silver", "raster/" + "a" * 2048 + ".tif")


def test_the_url_escapes_the_key():
    assert sts.object_url("geobase-silver", "raster/a b/c#1.tif") == (
        "https://lake.portal.test/geobase-silver/raster/a%20b/c%231.tif"
    )


# --- misses and failures ------------------------------------------------------


def test_anything_but_a_raster_is_not_found(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "raster_source_uri", lambda asset_id: None)

    assert as_viewer.get(url()).status_code == 404


@pytest.mark.parametrize(
    "setting",
    ["LAKE_PUBLIC_ENDPOINT", "LAKE_S3_ENDPOINT", "LAKE_STS_ACCESS_KEY", "LAKE_STS_SECRET_KEY"],
)
def test_without_its_settings_it_is_unavailable(as_viewer, a_raster, lake_sts, setting):
    setattr(lake_sts, setting, "")

    response = as_viewer.get(url())

    assert response.status_code == 503
    assert "does not serve rasters" in response.json()["detail"]


def test_a_public_endpoint_without_a_scheme_counts_as_unset(as_viewer, a_raster, lake_sts):
    lake_sts.LAKE_PUBLIC_ENDPOINT = "lake.portal.test:9000"

    assert as_viewer.get(url()).status_code == 503


def test_a_raster_outside_the_lake_is_a_lake_failure(as_viewer, monkeypatch):
    monkeypatch.setattr(kb, "raster_source_uri", lambda asset_id: "/data/rasters/local.tif")

    assert as_viewer.get(url()).status_code == 502


@pytest.mark.parametrize("code", ["AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"])
def test_the_lake_refusing_the_issuer_is_unavailable(as_viewer, a_raster, stub, code):
    stub.add_client_error("assume_role", service_error_code=code, http_status_code=403)

    assert as_viewer.get(url()).status_code == 503


def test_any_other_sts_error_is_a_lake_failure(as_viewer, a_raster, stub):
    stub.add_client_error(
        "assume_role", service_error_code="MalformedPolicyDocument", http_status_code=400
    )

    assert as_viewer.get(url()).status_code == 502


def test_an_unreachable_lake_is_unavailable(as_viewer, a_raster, lake_sts):
    """A real call to a port nothing listens on, not a stub: the error is botocore's own."""
    lake_sts.LAKE_S3_ENDPOINT = "127.0.0.1:1"
    sts.reset()

    assert as_viewer.get(url()).status_code == 503


def test_no_secret_reaches_the_log(as_viewer, a_raster, stub, caplog):
    expect_assume_role(stub)
    stub.add_client_error("assume_role", service_error_code="AccessDenied", http_status_code=403)

    with caplog.at_level(logging.DEBUG, logger="apps.map"):
        as_viewer.get(url())
        as_viewer.get(url())

    logged = caplog.text
    assert "Raster credentials for" in logged
    for secret in ("temporary-secret-placeholder", "temporary.session.token"):
        assert secret not in logged
    assert "issuer-password-placeholder" not in logged
