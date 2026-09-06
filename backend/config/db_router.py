"""
Database router enforcing the two-database split (docs/adr/002).

The knowledge base is owned by the data platform repo. This portal reads it
and never writes it. Read-only Postgres credentials are the real enforcement;
this router makes the rule mechanical inside Django too, so a future migration
cannot be pointed at `kb` by accident.
"""

KB_ALIAS = "kb"

# Apps whose models live in the knowledge base. Empty until the Map/Ask slices
# introduce read-only models; every app therefore routes to `portal` today.
KB_APP_LABELS: set[str] = set()


class KnowledgeBaseRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label in KB_APP_LABELS:
            return KB_ALIAS
        return "default"

    def db_for_write(self, model, **hints):
        # Nothing this repo owns is ever written to the knowledge base.
        if model._meta.app_label in KB_APP_LABELS:
            raise RuntimeError(
                f"Refusing to write to the knowledge base: {model._meta.label} "
                "is read-only (docs/adr/002)."
            )
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # Relations across the two databases are never valid.
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if labels & KB_APP_LABELS and not labels <= KB_APP_LABELS:
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # The portal never migrates the knowledge base — full stop.
        if db == KB_ALIAS:
            return False
        return app_label not in KB_APP_LABELS
