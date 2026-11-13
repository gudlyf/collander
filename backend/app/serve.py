"""Container entry point: listen on IPv4 and IPv6 when the host supports it.

Docker port forwarding may reach the container over IPv6 (``localhost`` often
resolves to ``::1`` first), so a plain IPv4 bind can leave the UI unreachable at
http://localhost. We open one dual-stack socket ourselves because asyncio marks
``::`` sockets as IPv6-only. Falls back to IPv4 where IPv6 is disabled.
Override with COLLANDER_HOST / COLLANDER_LISTEN_PORT.
"""

from __future__ import annotations

import os
import socket

import uvicorn


def _dual_stack_socket(port: int) -> socket.socket | None:
    if not socket.has_ipv6:
        return None
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", port))
    except OSError:
        sock.close()
        return None
    sock.set_inheritable(True)
    return sock


def main() -> None:
    port = int(os.environ.get("COLLANDER_LISTEN_PORT", "8000"))
    host = os.environ.get("COLLANDER_HOST")
    sock = None if host else _dual_stack_socket(port)
    config = uvicorn.Config(
        "app.main:app",
        host=host or ("::" if sock else "0.0.0.0"),
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(config)
    server.run(sockets=[sock] if sock else None)


if __name__ == "__main__":
    main()
