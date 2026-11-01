import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import admin, admin_auth, chat, public

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("signature")

app = FastAPI(
    title="Signature Auto Repair API",
    version="1.0.0",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


@app.middleware("http")
async def guard(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > settings.max_request_body_bytes):
        return JSONResponse({"detail": "La solicitud supera el tamaño permitido."}, status_code=413)
    if request.method in {"POST", "PUT", "PATCH"} and request.url.path.startswith("/api/"):
        content_type = request.headers.get("content-type", "")
        if length not in (None, "0") and not content_type.startswith("application/json"):
            return JSONResponse({"detail": "Tipo de contenido no admitido."}, status_code=415)
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Conversation-Token"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    fields = []
    for error in exc.errors():
        location = [str(p) for p in error.get("loc", []) if p not in ("body", "query", "path")]
        fields.append({"field": ".".join(location), "message": error.get("msg", "Valor inválido")})
    return JSONResponse({"detail": "Datos inválidos.", "fields": fields}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Se registra el tipo y la ruta; nunca se devuelven trazas al cliente.
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Ocurrió un error interno. Intente nuevamente."}, status_code=500)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


app.include_router(public.router)
app.include_router(chat.router)
app.include_router(admin_auth.router)
app.include_router(admin.router)
