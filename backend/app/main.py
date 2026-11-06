from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.meeting import router, unavailable
from app.config.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="W2M API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        coordinate_error = any(
            any(part in ("lat", "lon") for part in error["loc"])
            for error in exc.errors()
        )
        return JSONResponse(status_code=400, content={
            "error_code": "INVALID_COORDINATES" if coordinate_error else "INVALID_PARAMETERS",
            "message": "Tọa độ không hợp lệ." if coordinate_error else "Tham số không hợp lệ.",
            "request_id": request.state.request_id,
        })

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={
            "error_code": "INTERNAL_ERROR", "message": "Không thể xử lý yêu cầu.",
            "request_id": request.state.request_id,
        })

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "w2m", "version": "0.2.0"}

    @app.get("/ready", status_code=503)
    def ready(request: Request):
        return unavailable(request)

    app.include_router(router)
    return app


app = create_app()
