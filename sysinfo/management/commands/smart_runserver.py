import os
import socket
import sys

from django.conf import settings
from django.core.management.base import BaseCommand


PREFERRED_PORTS = [7777, 7778, 7779, 8000, 8080, 8888]
PORT_FILE = settings.BASE_DIR / "velour_port.txt"


def port_available(port):
    """Try to bind briefly to confirm the port is truly free."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            return True
    except OSError:
        return False


class Command(BaseCommand):
    help = "Start runserver on the first available port from the preferred list."

    def handle(self, *args, **options):
        port = None
        for candidate in PREFERRED_PORTS:
            if port_available(candidate):
                port = candidate
                break

        if port is None:
            self.stderr.write("No available port found in %s" % PREFERRED_PORTS)
            sys.exit(1)

        PORT_FILE.write_text(str(port))
        self.stdout.write("Velour starting on port %d (written to %s)" % (port, PORT_FILE))

        # exec into manage.py runserver so the reloader works cleanly —
        # call_command nests badly with the autoreloader.
        manage_py = str(settings.BASE_DIR / "manage.py")
        os.execvp(sys.executable, [
            sys.executable, manage_py, "runserver", "0.0.0.0:%d" % port,
        ])
