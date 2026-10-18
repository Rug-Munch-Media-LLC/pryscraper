"""Stdlib ``socket`` alias with a late-bound resolver.

The guard used to be a single module, so tests patch the resolver at
``pry.engine.url_guard.socket.getaddrinfo``. Both that seam and a patch of
stdlib ``socket.getaddrinfo`` must work, so the lookup happens at call time
instead of binding the function at import.
"""

from __future__ import annotations

import socket as _socket

AF_INET = _socket.AF_INET
AF_INET6 = _socket.AF_INET6
SOCK_STREAM = _socket.SOCK_STREAM
gaierror = _socket.gaierror


def getaddrinfo(*args, **kwargs):  # noqa: ANN002, ANN003 - stdlib passthrough
    """Resolve through the live stdlib function (patchable at either seam)."""
    return _socket.getaddrinfo(*args, **kwargs)


__all__ = ["AF_INET", "AF_INET6", "SOCK_STREAM", "gaierror", "getaddrinfo"]
