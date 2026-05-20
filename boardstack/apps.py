from django.apps import AppConfig


class BoardstackConfig(AppConfig):
    """Stack-of-CAs experimental app.  Isolated from caformer
    production paths (no QRPair writes, no chat dispatch
    interception)."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'boardstack'
