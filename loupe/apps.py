from django.apps import AppConfig


class LoupeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'loupe'
    verbose_name = 'loupe (Mandelbrot zoom + agent walks)'
