from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        # Registers the API-key scheme with drf-spectacular before any schema is built.
        from . import schema  # noqa: F401
