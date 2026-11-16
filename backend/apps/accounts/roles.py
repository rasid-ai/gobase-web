"""
The one place a user's role is decided.

A signed-in user with no profile row is a Viewer. Keeping that
fallback in a single resolver is what stops it drifting between the `me`
endpoint and the permission classes.
"""

from rest_framework.permissions import BasePermission

from .models import Role, UserProfile


def resolve_role(user) -> str:
    """Return the user's role, defaulting to Viewer when no profile exists."""
    if not user or not user.is_authenticated:
        return Role.VIEWER
    try:
        return user.profile.role
    except UserProfile.DoesNotExist:
        return Role.VIEWER


def is_admin(user) -> bool:
    return resolve_role(user) == Role.ADMIN


class IsAdmin(BasePermission):
    """
    Server-side Admin check.

    Unused until the Runs slice adds `POST /api/runs/trigger/`; it lives here
    so role logic has exactly one home.
    """

    message = "This action requires the Admin role."

    def has_permission(self, request, view) -> bool:
        return is_admin(request.user)
