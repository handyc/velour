from django.apps import AppConfig


class TableauConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tableau'
    verbose_name = 'Tableau — Tarski-style FOL world game (square + hex)'
