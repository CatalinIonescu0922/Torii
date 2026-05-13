"""
Status API server.

Reads the torri:ui:status snapshot from Redis and exposes it as
GET /api/status — the exact shape the React dashboard polls.

This is a separate process from the scheduler so it can run on
multiple replicas without any state of its own.
"""

import os
import json
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)

STATUS_KEY = "torri:ui:status"

EMPTY_RESPONSE = {
    "last_updated": datetime.now(timezone.utc).isoformat(),
    "pipelines": [],
}

_redis = redis_lib.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
)


@app.get("/api/status")
def get_status():
    try:
        raw = _redis.get(STATUS_KEY)
        if not raw:
            return EMPTY_RESPONSE
        return json.loads(raw)
    except Exception:
        return EMPTY_RESPONSE


@app.get("/health")
def health():
    return {"ok": True}
