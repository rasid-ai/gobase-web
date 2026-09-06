from django.conf import settings
from django.db import models


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
