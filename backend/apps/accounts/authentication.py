"""
API-key sign-in for desktop clients (docs/adr/020).

A desktop program sends `Authorization: Api-Key gbk_<prefix>_<secret>`. The
header word is its own, not `Bearer`: simplejwt claims every Bearer value and
rejects what it cannot read, and DRF stops at the first authenticator that
raises, so a key sent as Bearer would never reach this class.
"""

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.permissions import SAFE_METHODS

from .models import ApiKey


class ApiKeyAuthentication(BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword.lower().encode():
            return None  # Not ours; JWT has already had its turn.
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid API key header.")

        try:
            raw = parts[1].decode()
        except UnicodeDecodeError as exc:
            raise exceptions.AuthenticationFailed("Invalid API key header.") from exc

        key = ApiKey.find_active(raw)
        if key is None:
            raise exceptions.AuthenticationFailed("Invalid or revoked API key.")

        # A key can read, not act. This is checked here rather than in a
        # permission class because a view that sets its own permission_classes
        # (the Admin-only run trigger) would skip a default one.
        if request.method not in SAFE_METHODS:
            raise exceptions.PermissionDenied("API keys are read-only.")

        key.touch()
        return key.user, key

    def authenticate_header(self, request):
        return self.keyword
