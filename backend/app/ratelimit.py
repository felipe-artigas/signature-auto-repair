"""Limitador de tasa en memoria con ventana deslizante.

La aplicación corre en un único proceso de Uvicorn, por lo que un almacén en memoria es suficiente.
Si se escalara a varios procesos, este módulo es el único punto a reemplazar (por ejemplo, por Redis).
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str, limit: int, window_seconds: float) -> tuple[bool, float]:
        """Registra un intento. Devuelve (permitido, segundos hasta el próximo intento permitido)."""
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, max(0.0, bucket[0] + window_seconds - now)
            bucket.append(now)
            return True, 0.0

    def reset(self, prefix: str = "") -> None:
        with self._lock:
            for key in [k for k in self._hits if k.startswith(prefix)]:
                del self._hits[key]

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 300:
            return
        self._last_sweep = now
        for key in [k for k, v in self._hits.items() if not v or v[-1] < now - 3600]:
            del self._hits[key]


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Uvicorn se ejecuta con --proxy-headers y solo confía en Nginx local, por lo que
    # request.client.host ya contiene la IP real del visitante.
    return request.client.host if request.client else "desconocida"


def enforce(request: Request, bucket: str, limit: int, window_seconds: float, key: str | None = None) -> None:
    allowed, retry_after = limiter.hit(f"{bucket}:{key or client_ip(request)}", limit, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Intente nuevamente en unos minutos.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
