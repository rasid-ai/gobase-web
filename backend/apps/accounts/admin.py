from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Portal role"


class UserAdmin(DjangoUserAdmin):
    """Stock Django admin, with the portal role inlined (docs/adr/001)."""

    inlines = (UserProfileInline,)
    list_display = ("username", "email", "portal_role", "is_staff", "is_active")

    @admin.display(description="Portal role")
    def portal_role(self, obj: User) -> str:
        from .roles import resolve_role

        return resolve_role(obj)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
