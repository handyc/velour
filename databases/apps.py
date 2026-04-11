from django.apps import AppConfig


class DatabasesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'databases'
    verbose_name = 'Databases (MySQL / PostgreSQL connections)'
