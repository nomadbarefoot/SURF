#!/usr/bin/env python3
"""Start SURF on a local port with a small conflict check."""
import os
import socket
import sys

import uvicorn

from config.settings import get_settings


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def choose_port(host: str, preferred: int) -> int:
    if os.getenv("SURF_STRICT_PORT", "").lower() in {"1", "true", "yes"}:
        if port_available(host, preferred):
            return preferred
        raise RuntimeError(f"SURF startup port {preferred} is not available")

    candidates = [preferred, 17778]
    for port in candidates:
        if port_available(host, port):
            return port
    raise RuntimeError(f"No SURF startup port available from {candidates}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    settings = get_settings()
    settings.validate_runtime_security()
    port = choose_port(settings.host, settings.port)
    print(f"Starting SURF at http://{settings.host}:{port}")
    print(f"Health: http://{settings.host}:{port}/health")
    if settings.debug:
        print(f"Docs: http://{settings.host}:{port}/docs")

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
