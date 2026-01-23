from __future__ import annotations

import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.metrics import ERROR_COUNT, REQUEST_COUNT, REQUEST_LATENCY


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        route = request.scope.get("route")
        route_label = getattr(route, "path", None) or request.url.path
        method = request.method
        start = time.perf_counter()
        status_code = 500
        errored = False
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            errored = True
            raise
        finally:
            elapsed = time.perf_counter() - start
            REQUEST_LATENCY.labels(route=route_label, method=method).observe(elapsed)
            REQUEST_COUNT.labels(route=route_label, method=method, status=str(status_code)).inc()
            if status_code >= 500 or errored:
                ERROR_COUNT.labels(route=route_label, method=method).inc()
