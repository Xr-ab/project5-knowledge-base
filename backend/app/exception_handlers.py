from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import AppException

def register_exception_handlers(app: FastAPI):
    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException):
        return JSONResponse(
            content={"detail": exc.detail},
            status_code=exc.status_code
        )
       
