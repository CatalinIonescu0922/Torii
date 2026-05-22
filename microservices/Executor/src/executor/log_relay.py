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
        self.job_uuid = job_uuid
        self.key = f"{LOG_KEY_PREFIX}{job_uuid}"
        logger.info("[RELAY] Connecting to Redis: %s", redis_url.split("@")[-1])
        self._redis = redis_lib.from_url(redis_url, decode_responses=True)
        logger.info("[RELAY] Redis connection established for job: %s", job_uuid)
        self._line_count = 0

    def write(self, line: str) -> None:
        try:
            pipe = self._redis.pipeline()
            pipe.rpush(self.key, line)
            pipe.ltrim(self.key, -MAX_LINES, -1)
            pipe.expire(self.key, LOG_TTL)
            pipe.execute()
            self._line_count += 1
            if self._line_count % 50 == 0:
                logger.debug("[RELAY] %d lines written to Redis key=%s", self._line_count, self.key)
        except Exception as e:
            logger.error("[RELAY] Failed to write log line to Redis: %s", e)

    def write_eof(self) -> None:
        logger.info("[RELAY] EOF: job=%s total_lines=%d", self.job_uuid, self._line_count)
        self.write("__EOF__")
