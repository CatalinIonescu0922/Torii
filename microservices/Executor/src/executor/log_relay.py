"""
Log relay.

Writes job log lines to a Redis List so the status API can stream them
to the browser over WebSocket.

Key:  torri:log:{job_uuid}
TTL:  7 days (logs are kept long enough to review after a run)
Cap:  Last 5000 lines are kept (LTRIM after each RPUSH).
"""

import logging

import redis as redis_lib

logger = logging.getLogger("executor.log_relay")

LOG_KEY_PREFIX = "torri:log:"
LOG_TTL = 7 * 24 * 3600
MAX_LINES = 5000


class LogRelay:
    def __init__(self, job_uuid: str, redis_url: str):
        self.key = f"{LOG_KEY_PREFIX}{job_uuid}"
        self._redis = redis_lib.from_url(redis_url, decode_responses=True)

    def write(self, line: str) -> None:
        pipe = self._redis.pipeline()
        pipe.rpush(self.key, line)
        pipe.ltrim(self.key, -MAX_LINES, -1)
        pipe.expire(self.key, LOG_TTL)
        pipe.execute()

    def write_eof(self) -> None:
        """Write a sentinel so the WebSocket client knows the job is done."""
        self.write("__EOF__")
