import base64
import binascii
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app import config
from app.routes.api import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Synthetic Patient Data Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {"/api/health"}


def _password_ok(header: str, password: str) -> bool:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        _, _, given = base64.b64decode(encoded).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return secrets.compare_digest(given.encode(), password.encode())


@app.middleware("http")
async def require_password(request: Request, call_next):
    password = config.settings.app_password
    if password and request.url.path not in PUBLIC_PATHS:
        if not _password_ok(request.headers.get("authorization", ""), password):
            return Response(
                "Authentication required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Patient Data Generator"'},
            )
    return await call_next(request)


app.include_router(router)

if Path(config.settings.static_dir).is_dir():
    app.mount("/", StaticFiles(directory=config.settings.static_dir, html=True), name="frontend")
