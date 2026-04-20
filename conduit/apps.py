from django.apps import AppConfig


class ConduitConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'conduit'
    verbose_name = 'Conduit (pipelines & routing)'
