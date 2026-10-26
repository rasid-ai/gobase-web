from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.template.response import TemplateResponse

from .models import ApiKey, UserProfile


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


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    """
    Issue and revoke desktop API keys (docs/adr/020).

    Adding a key asks only for its user and name. The key is shown once, on the
    page right after, rendered into that response and nowhere else: not in a
    message, which would ride in a cookie to the next page.
    """

    list_display = ("name", "user", "prefix", "created_at", "last_used_at", "revoked_at")
    list_filter = (("revoked_at", admin.EmptyFieldListFilter),)
    search_fields = ("name", "prefix", "user__username")
    actions = ("revoke_keys",)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("user", "name")
        return ("user", "name", "prefix", "created_at", "last_used_at", "revoked_at")

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("user", "prefix", "created_at", "last_used_at", "revoked_at")

    def save_model(self, request, obj, form, change):
        if not change:
            request._issued_api_key = obj.assign_secret()
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        raw = getattr(request, "_issued_api_key", None)
        if raw is None:
            return super().response_add(request, obj, post_url_continue)
        context = {
            **self.admin_site.each_context(request),
            "title": "API key created",
            "opts": self.model._meta,
            "api_key": obj,
            "raw_key": raw,
        }
        return TemplateResponse(request, "admin/accounts/apikey/created.html", context)

    @admin.action(description="Revoke selected API keys")
    def revoke_keys(self, request, queryset):
        keys = list(queryset.filter(revoked_at=None))
        for key in keys:
            key.revoke()
        self.message_user(request, f"Revoked {len(keys)} API key(s).")
