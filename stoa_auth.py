"""
stoa_auth.py - Middleware de autenticacao por Bearer token para o STOA
Token configurado via STOA_TOKEN no .env
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

BYPASS_PATHS = {"/", "/manifest.webmanifest", "/sw.js", "/status", "/ws", "/api/health", "/api/preview/health", "/api/memory/recent"}
BYPASS_PREFIXES = ("/icons/", "/api/", "/logs/")


def _get_configured_token() -> Optional[str]:
    return os.getenv("STOA_TOKEN") or None


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = _get_configured_token()

        if not token:
            return await call_next(request)

        path = request.url.path

        if path in BYPASS_PATHS:
            return await call_next(request)

        if any(path.startswith(p) for p in BYPASS_PREFIXES):
            return await call_next(request)

        if path == "/ws":
            qs_token = request.query_params.get("token", "")
            if qs_token == token:
                return await call_next(request)
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {token}":
            return await call_next(request)

        # DEV MODE: aceitar todas as requisições sem token a menos que STOA_AUTH_STRICT=true
        if os.getenv("STOA_AUTH_STRICT", "false").lower() != "true":
            return await call_next(request)

        return JSONResponse({"detail": "Unauthorized"}, status_code=401)


def validate_ws_token(token_param: Optional[str]) -> bool:
    token = _get_configured_token()
    if not token:
        return True
    return token_param == token
