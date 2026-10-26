"""How the API-key sign-in appears in openapi.yaml. Loaded by AccountsConfig.ready()."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.ApiKeyAuthentication"
    name = "apiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": (
                "`Api-Key <key>`, for desktop clients. Read-only: any method other than "
                "GET, HEAD or OPTIONS is refused with 403 (docs/adr/020)."
            ),
        }
