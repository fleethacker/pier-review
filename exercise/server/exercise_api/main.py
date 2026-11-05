"""The exercise simulator's own service: a shared scenario library, the public map token and a client error log.

The simulator itself runs in the browser, so this service is optional — without it the app keeps scenarios in the browser
and asks for a map token. Run it with `make serve` in this directory, or:

    uvicorn exercise_api.main:app --port 8200
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

API_PREFIX = "/api/v1"

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Exercise simulator service",
    version="0.1.0",
    description="Shared scenario library, map token and client error log for the exercise simulator.",
)

# The page is served from the same origin in a deployment; in development it is on another port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4100", "http://127.0.0.1:4100"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=API_PREFIX)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
