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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# DRF — default-deny. HLR-001 holds structurally: a new endpoint is protected
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
    # Rotation + blacklist are what make HLR-004 ("revoked refresh credential")
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
