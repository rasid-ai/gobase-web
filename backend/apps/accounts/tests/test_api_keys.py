"""API-key sign-in for desktop clients (docs/adr/020, specs/api-keys.md)."""

import re
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from apps.accounts.models import ApiKey

pytestmark = pytest.mark.django_db

KEY_PATTERN = re.compile(r"gbk_[0-9a-f]{12}_[A-Za-z0-9_-]{43}")

# Admin pages load static files. Plain storage keeps these tests independent of
# whichever static-files backend production settings choose.
PLAIN_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


def with_key(api, raw):
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return api


@pytest.fixture
def superuser_client(client, django_user_model):
    """A Django admin session. Not pytest-django's admin_client: this package's
    `admin_user` fixture is a portal Admin, not a superuser, and it shadows the one
    admin_client would log in with."""
    superuser = django_user_model.objects.create_superuser("key-admin", password="unused-1234")
    client.force_login(superuser)
    return client


# --- Issuing --------------------------------------------------------------------


def test_issue_returns_the_key_and_stores_only_its_hash(viewer):
    key, raw = ApiKey.issue(viewer, "laptop")

    assert KEY_PATTERN.fullmatch(raw)
    assert raw.startswith(f"gbk_{key.prefix}_")
    assert ":" not in raw  # so it can later serve as a Basic-auth password
    stored = ApiKey.objects.filter(pk=key.pk).values().get()
    assert raw not in {str(value) for value in stored.values()}


# --- Signing in -----------------------------------------------------------------


def test_a_key_signs_in_as_its_owner(api, viewer):
    _, raw = ApiKey.issue(viewer, "laptop")

    response = with_key(api, raw).get("/api/auth/me")

    assert response.status_code == 200
    assert response.data == {"username": viewer.username, "role": "viewer"}


def test_a_key_carries_its_owners_role(api, admin_user):
    _, raw = ApiKey.issue(admin_user, "laptop")

    assert with_key(api, raw).get("/api/auth/me").data["role"] == "admin"


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda raw: raw[:-1] + ("A" if raw[-1] != "A" else "B"), id="wrong-secret"),
        pytest.param(lambda raw: "gbk_000000000000_" + raw.split("_", 2)[2], id="unknown-prefix"),
        pytest.param(lambda raw: "xyz" + raw[3:], id="wrong-label"),
        pytest.param(lambda raw: "gbk_", id="truncated"),
        pytest.param(lambda raw: "not-a-key", id="garbage"),
    ],
)
def test_a_bad_key_is_refused_with_401(api, viewer, mangle):
    _, raw = ApiKey.issue(viewer, "laptop")

    response = with_key(api, mangle(raw)).get("/api/auth/me")

    assert response.status_code == 401
    assert "username" not in response.data


def test_a_malformed_header_is_refused(api, viewer):
    _, raw = ApiKey.issue(viewer, "laptop")
    api.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw} extra")

    assert api.get("/api/auth/me").status_code == 401


def test_a_revoked_key_is_refused(api, viewer):
    key, raw = ApiKey.issue(viewer, "laptop")
    key.revoke()

    assert with_key(api, raw).get("/api/auth/me").status_code == 401


def test_a_disabled_users_key_is_refused(api, viewer):
    _, raw = ApiKey.issue(viewer, "laptop")
    viewer.is_active = False
    viewer.save()

    assert with_key(api, raw).get("/api/auth/me").status_code == 401


def test_a_key_sent_as_bearer_is_refused(api, viewer):
    """The reason for the Api-Key word: simplejwt rejects any Bearer value it cannot read."""
    _, raw = ApiKey.issue(viewer, "laptop")
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")

    assert api.get("/api/auth/me").status_code == 401


# --- Read-only ------------------------------------------------------------------


def test_a_key_cannot_change_the_password(api, viewer):
    _, raw = ApiKey.issue(viewer, "laptop")

    response = with_key(api, raw).post(
        "/api/auth/change-password",
        {"current_password": "anything", "new_password": "a-new-long-password-1"},
        format="json",
    )

    assert response.status_code == 403
    viewer.refresh_from_db()
    assert not viewer.check_password("a-new-long-password-1")


def test_an_admins_key_is_read_only_too(api, admin_user):
    _, raw = ApiKey.issue(admin_user, "laptop")

    assert with_key(api, raw).post("/api/auth/logout", {}, format="json").status_code == 403


def test_a_bad_key_on_a_write_is_401_not_403(api, viewer):
    """A wrong key says so before the read-only rule is reached."""
    response = with_key(api, "gbk_000000000000_nope").post("/api/auth/logout", {}, format="json")

    assert response.status_code == 401


# --- Last used ------------------------------------------------------------------


def test_last_used_is_recorded_but_not_on_every_request(api, viewer):
    key, raw = ApiKey.issue(viewer, "laptop")
    assert key.last_used_at is None

    with_key(api, raw).get("/api/auth/me")
    key.refresh_from_db()
    first = key.last_used_at
    assert first is not None

    with_key(api, raw).get("/api/auth/me")
    key.refresh_from_db()
    assert key.last_used_at == first  # within the resolution: no write

    ApiKey.objects.filter(pk=key.pk).update(
        last_used_at=first - ApiKey.LAST_USED_RESOLUTION - timedelta(seconds=1)
    )
    with_key(api, raw).get("/api/auth/me")
    key.refresh_from_db()
    assert key.last_used_at > first - timedelta(seconds=1)


# --- Issuing from the shell and from admin --------------------------------------


def test_the_command_prints_a_working_key(api, viewer):
    out, err = StringIO(), StringIO()

    call_command("create_api_key", viewer.username, "laptop", stdout=out, stderr=err)

    raw = out.getvalue().strip()
    assert KEY_PATTERN.fullmatch(raw)
    assert "not stored" in err.getvalue()
    assert with_key(api, raw).get("/api/auth/me").status_code == 200


def test_the_command_refuses_an_unknown_user():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("create_api_key", "nobody", "laptop", stdout=StringIO())


@PLAIN_STATIC
def test_admin_shows_a_new_key_once_and_it_works(superuser_client, api, viewer):
    response = superuser_client.post(
        reverse("admin:accounts_apikey_add"), {"user": viewer.pk, "name": "laptop"}
    )

    assert response.status_code == 200
    raw = KEY_PATTERN.search(response.content.decode()).group(0)
    assert with_key(api, raw).get("/api/auth/me").data["username"] == viewer.username

    key = ApiKey.objects.get(name="laptop")
    change_page = superuser_client.get(reverse("admin:accounts_apikey_change", args=[key.pk]))
    assert raw not in change_page.content.decode()


@PLAIN_STATIC
def test_admin_revokes_keys(superuser_client, api, viewer):
    key, raw = ApiKey.issue(viewer, "laptop")

    superuser_client.post(
        reverse("admin:accounts_apikey_changelist"),
        {"action": "revoke_keys", "_selected_action": [key.pk]},
    )

    key.refresh_from_db()
    assert key.revoked_at is not None
    assert key.revoked_at <= timezone.now()
    assert with_key(api, raw).get("/api/auth/me").status_code == 401


# --- Contract -------------------------------------------------------------------


def test_the_schema_offers_the_key_on_protected_endpoints():
    schema = SchemaGenerator().get_schema(request=None, public=True)

    scheme = schema["components"]["securitySchemes"]["apiKeyAuth"]
    assert scheme == {**scheme, "type": "apiKey", "in": "header", "name": "Authorization"}
    assert {"apiKeyAuth": []} in schema["paths"]["/api/auth/me"]["get"]["security"]
    assert {"apiKeyAuth": []} not in schema["paths"]["/api/auth/login"]["post"]["security"]
