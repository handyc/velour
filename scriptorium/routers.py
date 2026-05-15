"""DB router that pins DANWSI's `inscriptions` app to a separate
database connection (the danwsi sqlite file), while Scriptorium's own
models and the rest of Velour stay on `default`.

DANWSI manages its own migrations from its own checkout, so this router
*never* lets Velour's migrate touch the inscriptions tables. If you
want to inspect / read / write Inscription, Word, ContentData, etc.
from inside Velour you get to — but schema lifecycle stays with
DANWSI's own `manage.py migrate`.
"""

INSCRIPTIONS_APP = 'inscriptions'
DANWSI_DB = 'danwsi'


class InscriptionsRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == INSCRIPTIONS_APP:
            return DANWSI_DB
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == INSCRIPTIONS_APP:
            return DANWSI_DB
        return None

    def allow_relation(self, obj1, obj2, **hints):
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        # HighlightStack.created_by points at auth.User. We don't enforce FK
        # across DBs, but we don't want to *block* the lookup either.
        if INSCRIPTIONS_APP in labels:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == INSCRIPTIONS_APP:
            # DANWSI owns its own migrations; never apply them from Velour.
            return False
        if db == DANWSI_DB:
            # Don't pollute the danwsi sqlite with Velour's tables.
            return False
        return None
