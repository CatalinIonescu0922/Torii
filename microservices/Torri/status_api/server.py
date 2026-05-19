"""
Status API server.

Reads state from Redis and exposes it over HTTP and WebSocket.

Endpoints:
  GET  /api/status                     — full pipeline snapshot (polled by dashboard)
  GET  /api/buildset/{buildset_uuid}   — single buildset detail
  GET  /ws/job/{job_uuid}/logs         — WebSocket: stream log lines for a job
"""

import asyncio
import json
import os
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)

STATUS_KEY = "torri:ui:status"
BUILDSET_KEY_PREFIX = "torri:buildset:"
LOG_KEY_PREFIX = "torri:log:"

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


@app.get("/api/buildset/{buildset_uuid}")
def get_buildset(buildset_uuid: str):
    try:
        raw = _redis.get(f"{BUILDSET_KEY_PREFIX}{buildset_uuid}")
        if not raw:
            return {"error": "not found"}, 404
        return json.loads(raw)
    except Exception:
        return {"error": "internal error"}, 500


@app.websocket("/ws/job/{job_uuid}/logs")
async def job_logs(websocket: WebSocket, job_uuid: str):
    """
    Stream log lines for a job.

    Sends all lines already in Redis, then polls for new lines every 200ms
    until the EOF sentinel (__EOF__) is seen.
    """
    await websocket.accept()
    key = f"{LOG_KEY_PREFIX}{job_uuid}"
    cursor = 0

    try:
        while True:
            lines = _redis.lrange(key, cursor, -1)
            for line in lines:
                cursor += 1
                await websocket.send_text(line)
                if line == "__EOF__":
                    return
            # No new lines yet — wait before polling again.
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass


@app.get("/health")
def health():
    return {"ok": True}
