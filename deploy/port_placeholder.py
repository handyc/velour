#!/usr/bin/env python3
"""Bind one or more TCP ports at WSL boot so mirrored-networking
registers them with the Windows host.

Why: with networkingMode=mirrored + hostAddressLoopback=true, WSL's
IPv4 127.0.0.1 routes through Windows, which builds its WSL-listener
table at VM boot. Listeners bound later are unreachable over IPv4.
Keeping placeholder listeners alive from supervisor makes the ports
reachable today; when a real staging app is ready for a port, drop
the port from this script's arg list and add a dedicated supervisor
program on it.

Usage (from supervisor): port_placeholder.py 7778 7779 7780 7781 7782
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class Placeholder(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            f"Port {self.server.server_port} reserved by Velour supervisor "
            f"(deploy/port_placeholder.py). Swap to a real app via "
            f"deploy/supervisor-wsl.conf.\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a, **_kw):
        pass


def serve(port):
    HTTPServer(("0.0.0.0", port), Placeholder).serve_forever()


def main(ports):
    threads = [threading.Thread(target=serve, args=(p,), daemon=False)
               for p in ports]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: port_placeholder.py <port> [<port> ...]", file=sys.stderr)
        sys.exit(2)
    main([int(p) for p in sys.argv[1:]])
