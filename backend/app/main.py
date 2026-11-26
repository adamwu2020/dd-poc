import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import auth, billing, config, db
from app.jobs import recover_interrupted_jobs
from app.routes.api import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db(config.settings.database_url)
    await recover_interrupted_jobs()
    yield
    await db.close_db()


app = FastAPI(title="Synthetic Patient Data Generator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(router)

if Path(config.settings.static_dir).is_dir():
    app.mount("/", StaticFiles(directory=config.settings.static_dir, html=True), name="frontend")
