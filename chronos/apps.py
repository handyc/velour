from django.apps import AppConfig


class ChronosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chronos'
    verbose_name = 'Chronos (time + timezones)'
