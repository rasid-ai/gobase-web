"""Tests for the behaviour described in specs/auth.md."""

from datetime import timedelta

import pytest
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tests.conftest import PASSWORD

COOKIE = settings.REFRESH_COOKIE_NAME

pytestmark = pytest.mark.django_db


def login(api, user):
    response = api.post(
        "/api/auth/login",
        {"username": user.username, "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    return response


def bearer(api, access):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


# --- Authentication required everywhere but login ----------------------------


@pytest.mark.parametrize(
    "method,path",
    [("get", "/api/auth/me"), ("post", "/api/auth/change-password")],
)
def test_endpoints_require_authentication(api, method, path):
    """GIVEN no valid session, any /api/ endpoint except login answers 401."""
    response = api.get(path) if method == "get" else api.post(path, {}, format="json")
    assert response.status_code == 401
    assert "username" not in response.data
    assert "role" not in response.data


def test_login_is_reachable_without_a_session(api, viewer):
    assert login(api, viewer).status_code == 200


# --- The session survives a page refresh -------------------------------------


def test_login_sets_httponly_refresh_cookie_and_returns_access(api, viewer):
    response = login(api, viewer)
    assert response.data["access"]
    # The refresh credential must never be readable by JavaScript and must
    # never appear in a response body — the session rests on both facts.
    assert "refresh" not in response.data
    cookie = response.cookies[COOKIE]
    assert cookie["httponly"] is True
    assert cookie["path"] == settings.REFRESH_COOKIE_PATH


def test_session_survives_a_reload(api, viewer):
    """A reload loses the in-memory access token; the cookie alone restores it."""
    first = login(api, viewer)
    api.credentials()  # the reload: every in-memory credential is gone

    refreshed = api.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.data["access"] != first.data["access"]

    bearer(api, refreshed.data["access"])
    assert api.get("/api/auth/me").status_code == 200


def test_bad_credentials_start_no_session(api, viewer):
    response = api.post(
        "/api/auth/login",
        {"username": viewer.username, "password": "wrong"},
        format="json",
    )
    assert response.status_code == 400
    assert COOKIE not in response.cookies


# --- Transparent renewal -----------------------------------------------------


def test_expired_access_token_is_rejected_then_renewed(api, viewer):
    """
    GIVEN an expired access token and a valid refresh credential
    WHEN the user acts THEN the action completes.

    The backend half: the expired token is refused, the cookie yields a fresh
    one, and the retry succeeds. The SPA's interceptor makes it invisible.
    """
    login(api, viewer)

    expired = RefreshToken.for_user(viewer).access_token
    expired.set_exp(lifetime=timedelta(seconds=-1))
    bearer(api, str(expired))
    assert api.get("/api/auth/me").status_code == 401

    api.credentials()
    renewed = api.post("/api/auth/refresh")
    assert renewed.status_code == 200

    bearer(api, renewed.data["access"])
    assert api.get("/api/auth/me").status_code == 200


def test_refresh_rotates_the_cookie(api, viewer):
    """Rotation is what limits the blast radius of a stolen cookie."""
    original = login(api, viewer).cookies[COOKIE].value
    api.credentials()
    rotated = api.post("/api/auth/refresh").cookies[COOKIE].value
    assert rotated != original


# --- An unrenewable session ends ---------------------------------------------


def test_revoked_refresh_credential_ends_the_session(api, viewer):
    login(api, viewer)
    api.credentials()

    # Rotation blacklists the old token; replaying it is the revoked case.
    stale = api.cookies[COOKIE].value
    assert api.post("/api/auth/refresh").status_code == 200

    api.cookies[COOKIE] = stale
    response = api.post("/api/auth/refresh")
    assert response.status_code == 401
    assert response.cookies[COOKIE].value == ""  # the cookie is cleared with it
    assert "access" not in response.data


def test_refresh_without_a_cookie_is_unauthorised(api):
    response = api.post("/api/auth/refresh")
    assert response.status_code == 401
    assert "access" not in response.data


def test_logout_revokes_the_session(api, viewer):
    login_response = login(api, viewer)
    bearer(api, login_response.data["access"])

    assert api.post("/api/auth/logout").status_code == 204
    api.credentials()
    assert api.post("/api/auth/refresh").status_code == 401


# --- Identity and role exposed to the client ---------------------------------


def test_me_returns_username_and_role_for_a_viewer(api, viewer):
    bearer(api, login(api, viewer).data["access"])
    response = api.get("/api/auth/me")
    assert response.status_code == 200
    assert response.data == {"username": "viewer-user", "role": "viewer"}


def test_me_returns_admin_role_for_an_admin(api, admin_user):
    bearer(api, login(api, admin_user).data["access"])
    assert api.get("/api/auth/me").data["role"] == "admin"


# --- Password change ---------------------------------------------------------


def test_wrong_current_password_is_rejected(api, viewer):
    bearer(api, login(api, viewer).data["access"])
    response = api.post(
        "/api/auth/change-password",
        {"current_password": "wrong", "new_password": "a-brand-new-secret-42"},
        format="json",
    )
    assert response.status_code == 400
    viewer.refresh_from_db()
    assert viewer.check_password(PASSWORD)  # unchanged


def test_correct_current_password_changes_it(api, viewer):
    bearer(api, login(api, viewer).data["access"])
    new_password = "a-brand-new-secret-42"
    response = api.post(
        "/api/auth/change-password",
        {"current_password": PASSWORD, "new_password": new_password},
        format="json",
    )
    assert response.status_code == 204

    # The next login succeeds only with the new password.
    api.credentials()
    api.cookies.clear()
    assert (
        api.post(
            "/api/auth/login",
            {"username": viewer.username, "password": PASSWORD},
            format="json",
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/api/auth/login",
            {"username": viewer.username, "password": new_password},
            format="json",
        ).status_code
        == 200
    )


# --- No profile means Viewer -------------------------------------------------


def test_user_without_a_profile_reads_as_viewer(api, profileless):
    bearer(api, login(api, profileless).data["access"])
    response = api.get("/api/auth/me")
    assert response.status_code == 200
    assert response.data["role"] == "viewer"


def test_is_admin_is_false_without_a_profile(profileless):
    from apps.accounts.roles import is_admin

    assert is_admin(profileless) is False
