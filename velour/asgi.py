"""ASGI config for velour.

HTTP traffic flows through Django; WebSocket traffic is routed by
Channels into per-app consumers (currently just the web terminal's
PTY proxy). AuthMiddlewareStack populates ``scope['user']`` on the
WS handshake from the session cookie, the same way HTTP does.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'velour.settings')

# Instantiate the Django ASGI app *before* importing any code that
# touches Django models — otherwise app loading races consumer imports.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from terminal.routing import websocket_urlpatterns as terminal_ws  # noqa: E402


application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(terminal_ws)),
    ),
})
