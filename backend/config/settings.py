"""
Django settings for Geo Portal.

Secrets are read by name from the environment, never written here.
See context/architecture.md and CLAUDE.md.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me-before-any-deploy")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "apps.accounts",
    "apps.catalog",
    "apps.map",
    "apps.places",
    "apps.runs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves Django admin's own static files from inside the container, so a
    # rollback to an old image gets that image's static files (docs/adr/007).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Two databases, one instance (docs/adr/002).
#   default -> `portal`, read-write, owned by this repo.
#   kb      -> knowledge base, READ-ONLY, owned by the data platform repo.
# The router in config/db_router.py makes the read-only rule mechanical.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("PORTAL_DB_NAME", "portal"),
        "USER": env("PORTAL_DB_USER", os.environ.get("USER", "postgres")),
        "PASSWORD": os.environ.get("PORTAL_DB_PASSWORD", ""),
        "HOST": env("PORTAL_DB_HOST", "localhost"),
        "PORT": env("PORTAL_DB_PORT", "5432"),
    },
    "kb": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("KB_DB_NAME", "kb"),
        "USER": env("KB_DB_USER", os.environ.get("USER", "postgres")),
        "PASSWORD": os.environ.get("KB_DB_PASSWORD", ""),
        "HOST": env("KB_DB_HOST", "localhost"),
        "PORT": env("KB_DB_PORT", "5432"),
        # Never connect eagerly: no slice before Map/Ask touches this alias.
        "OPTIONS": {},
        "TEST": {"MIRROR": "default"},
    },
}

DATABASE_ROUTERS = ["config.db_router.KnowledgeBaseRouter"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Prefixed rather than the default "static/": in production the host nginx
# routes this prefix to the backend while everything else goes to the SPA
# container, so it must not collide with anything Vite emits (docs/adr/007).
STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Admin is reachable in production (docs/adr/007), which puts Django's session
# and CSRF cookies on the same public origin as the JWT surface. Both default
# to Secure wherever DEBUG is off; neither is related to the refresh cookie.
#
# The override exists for one case: a first bring-up on a host that has no
# certificate yet, reached over http by IP. A browser will not store a Secure
# cookie over http, so with these left on, signing in silently fails. Turning
# them off ships session and CSRF cookies in clear text — acceptable only
# while nothing real is behind the login, and to be removed the moment TLS is
# in place.
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = True

# Behind the host nginx, which terminates TLS. Without this Django sees plain
# http on every proxied request and Secure cookies never stick.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# ---------------------------------------------------------------------------
# DRF — default-deny, structurally: a new endpoint is protected
# unless it explicitly opts out, so it cannot be forgotten.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

ACCESS_TOKEN_LIFETIME_MINUTES = int(env("ACCESS_TOKEN_LIFETIME_MINUTES", "15"))
REFRESH_TOKEN_LIFETIME_DAYS = int(env("REFRESH_TOKEN_LIFETIME_DAYS", "7"))

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=ACCESS_TOKEN_LIFETIME_MINUTES),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=REFRESH_TOKEN_LIFETIME_DAYS),
    # Rotation + blacklist are what make a revoked refresh credential
    # and sign-out real rather than advisory.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# The refresh token lives only in this cookie; the access token lives only in
# the SPA's memory. Path scoping keeps the cookie off every non-auth request.
REFRESH_COOKIE_NAME = env("REFRESH_COOKIE_NAME", "gp_refresh")
REFRESH_COOKIE_PATH = "/api/auth"
REFRESH_COOKIE_SECURE = env_bool("REFRESH_COOKIE_SECURE", not DEBUG)
REFRESH_COOKIE_SAMESITE = env("REFRESH_COOKIE_SAMESITE", "Lax")

SPECTACULAR_SETTINGS = {
    "TITLE": "Geo Portal API",
    "DESCRIPTION": "Internal API for the Geo Portal SPA. Read-only over the knowledge base.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api",
}

# Dagster — the pipeline orchestrator. Reached only over its GraphQL API, and
# only from apps/runs/dagster.py (docs/adr/004). Field names, quirks and how to
# confirm the two names below are in context/integrations/dagster.md.
# Every one carries a default: config.settings.env raises without one, and CI's
# contract job sets no Dagster variables at all.
DAGSTER_GRAPHQL_URL = env("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3000/graphql")
DAGSTER_REPOSITORY_LOCATION = env("DAGSTER_REPOSITORY_LOCATION", "gobase_orchestration.definitions")
DAGSTER_REPOSITORY = env("DAGSTER_REPOSITORY", "__repository__")
DAGSTER_JOB_NAME = env("DAGSTER_JOB_NAME", "weekly_pipeline")
DAGSTER_TIMEOUT_SECONDS = float(env("DAGSTER_TIMEOUT_SECONDS", "5"))

# The geocoder — the one outside service the portal does not run itself. Only
# apps/places/esri.py speaks to it (docs/adr/011); context/integrations/esri.md
# has the request shape and the terms that bound it.
# Defaults on every one, for the same reason as Dagster's: config.settings.env
# raises without one and CI's contract job sets no variables at all. A blank
# key is meaningful rather than missing -- the endpoint answers 503 and the
# page says address search is unavailable, so the portal runs without an
# account.
ESRI_GEOCODE_URL = env(
    "ESRI_GEOCODE_URL",
    "https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer",
)
ESRI_API_KEY = env("ESRI_API_KEY", "")
ESRI_TIMEOUT_SECONDS = float(env("ESRI_TIMEOUT_SECONDS", "5"))
# How many candidates one search may offer. The dropdown shows all of them.
ESRI_MAX_CANDIDATES = int(env("ESRI_MAX_CANDIDATES", "5"))

# --- the lake (S3-compatible object storage) --------------------------------
# The silver bucket holds the GeoParquet the Map reads through DuckDB (GP-4).
# Nothing here names a provider: RustFS, MinIO and AWS S3 differ only in these
# values, so moving between them is a .env edit and a restart.
#
# Endpoint blank means AWS's own. `path` URL style suits RustFS and MinIO,
# `vhost` suits AWS. Blank credentials hand over to DuckDB's credential chain,
# which is how an instance role is used instead of static keys.
LAKE_S3_ENDPOINT = env("LAKE_S3_ENDPOINT", "")
# AWS needs the bucket's real region; MinIO and RustFS ignore it entirely, so
# leaving it blank there is correct rather than merely tolerated.
LAKE_S3_REGION = env("LAKE_S3_REGION", "")
LAKE_S3_ACCESS_KEY = env("LAKE_S3_ACCESS_KEY", "")
LAKE_S3_SECRET_KEY = env("LAKE_S3_SECRET_KEY", "")
LAKE_S3_USE_SSL = env_bool("LAKE_S3_USE_SSL", True)
LAKE_S3_URL_STYLE = env("LAKE_S3_URL_STYLE", "vhost")
# The most features in one page of an asset's features, and the most a caller
# may ask for. The query asks for one row more than this to tell a full page
# from the last one. It caps a page, not an asset: a caller walks the pages.
#
# The client's PAGE_SIZE (frontend/src/features/workspace/useAssetFeatures.ts)
# asks for this many; if it asks for more, this cap quietly wins, so raise the
# two together. Most of a page's cost is building each feature as JSON, not the
# scan — the measurements are in that file — so a bigger page mostly saves
# round trips.
LAKE_PAGE_SIZE = int(env("LAKE_PAGE_SIZE", "10000"))
