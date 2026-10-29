import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    VIEWER = "viewer", "Viewer"


class UserProfile(models.Model):
    """
    Role carrier for a portal user (context/architecture.md).

    One-to-one onto the stock Django user so roles are managed from stock
    Django admin. A user with no profile row reads as Viewer — see
    `resolve_role`; that fallback is HLR-008 and belongs there, not here.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        verbose_name = "user profile"
        verbose_name_plural = "user profiles"

    def __str__(self) -> str:
        return f"{self.user.username} ({self.role})"


def _hash_key(raw: str) -> str:
    # A key is 256 random bits, so a fast hash is enough: there is nothing to brute-force.
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKey(models.Model):
    """
    A long-lived credential for a desktop client, tied to one user (docs/adr/021).

    The key reads as its owner, with the owner's role, and only on safe methods
    (`apps.accounts.authentication`). It looks like `gbk_<prefix>_<secret>`:
    the prefix finds the row and the hash checks the whole key. The key itself
    is shown once, when it is made, and never stored.
    """

    LABEL = "gbk"

    # `last_used_at` tells an Admin whether a key is still in use; it is not an
    # audit log. Writing it on every request would turn each read into a write.
    LAST_USED_RESOLUTION = timedelta(minutes=5)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    name = models.CharField(max_length=100, help_text="What the key is for, e.g. “Ali's laptop”.")
    prefix = models.CharField(max_length=16, unique=True, editable=False)
    key_hash = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "API key"
        verbose_name_plural = "API keys"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    def assign_secret(self) -> str:
        """Give an unsaved key its prefix and hash; return the key, which is not kept."""
        self.prefix = secrets.token_hex(6)
        raw = f"{self.LABEL}_{self.prefix}_{secrets.token_urlsafe(32)}"
        self.key_hash = _hash_key(raw)
        return raw

    @classmethod
    def issue(cls, user, name: str) -> tuple["ApiKey", str]:
        key = cls(user=user, name=name)
        raw = key.assign_secret()
        key.save()
        return key, raw

    @classmethod
    def issue_replacing(cls, user, name: str) -> tuple["ApiKey", str]:
        """Issue a key and revoke the user's other live keys of the same name.

        A desktop client names its key after the computer, so signing in again
        from that computer leaves one live key there, not one per sign-in.
        """
        with transaction.atomic():
            cls.objects.filter(user=user, name=name, revoked_at=None).update(
                revoked_at=timezone.now()
            )
            return cls.issue(user, name)

    @classmethod
    def find_active(cls, raw: str) -> "ApiKey | None":
        """The live key `raw` names, or None: unknown, wrong secret, revoked, or user disabled."""
        label, _, rest = raw.partition("_")
        prefix, _, secret = rest.partition("_")
        if label != cls.LABEL or not prefix or not secret:
            return None

        key = cls.objects.select_related("user").filter(prefix=prefix, revoked_at=None).first()
        if key is None or not key.user.is_active:
            return None
        if not hmac.compare_digest(key.key_hash, _hash_key(raw)):
            return None
        return key

    def touch(self) -> None:
        """Record use, at most once per LAST_USED_RESOLUTION."""
        now = timezone.now()
        if self.last_used_at and now - self.last_used_at < self.LAST_USED_RESOLUTION:
            return
        ApiKey.objects.filter(pk=self.pk).update(last_used_at=now)
        self.last_used_at = now

    def revoke(self) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])
