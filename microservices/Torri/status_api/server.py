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
import logging
import os
import websockets
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
logger = logging.getLogger(__name__)

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
    os.getenv("REDIS_URL", "redis://redis:6379/0"),
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

    logger.info("WebSocket connected for job_uuid=%s key=%s", job_uuid, key)

    try:
        while True:
            try:
                lines = _redis.lrange(key, cursor, -1)
            except Exception as exc:
                logger.warning("Redis read failed for job_uuid=%s: %s", job_uuid, exc)
                await asyncio.sleep(1.0)
                continue

            for line in lines:
                cursor += 1
                try:
                    await websocket.send_text(line)
                except WebSocketDisconnect:
                    logger.info("WebSocket disconnected while sending job_uuid=%s", job_uuid)
                    return
                except Exception as exc:
                    logger.warning("WebSocket send failed for job_uuid=%s: %s", job_uuid, exc)
                    return

                if line == "__EOF__":
                    try:
                        await websocket.close(code=1000)
                    except Exception:
                        pass
                    return

            # No new lines yet — wait before polling again.
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for job_uuid=%s", job_uuid)
    except Exception as exc:
        logger.exception("Unexpected websocket error for job_uuid=%s: %s", job_uuid, exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@app.get("/health")
def health():
    return {"ok": True}
