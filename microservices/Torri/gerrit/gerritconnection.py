import json
import time
import requests
import threading
from dataclasses import dataclass
from cachetools import LRUCache
from shared.logger_setup import get_logger
from queue import Empty, Queue
from typing import Any, Optional
from shared.gerritmodel import GerritTriggerEvent
from connection import BaseConnection
from shared.gerritmodel import known_events
from concurrent.futures import ThreadPoolExecutor

class GerritEventProcessor(threading.Thread):
    logger = get_logger("torri.gerrit.event_processor")
    def __init__(self, kafka_connection, gerrit_connection) -> None:
        super().__init__(name="GerritEventProcessor", daemon=True)
        self.kafka_connection = kafka_connection
        self.gerrit_connection = gerrit_connection
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        self.connection.addEvent(None)

    def _build_event(self, data: dict[str, Any]) -> GerritTriggerEvent:
        event = GerritTriggerEvent()
        event.type = str(data.get("type", "unknown"))
        if event.type not in known_events:
            self.logger.debug("Skip unknown event")
            return
        event.comment = str(data.get("comment", ""))

        change = data.get("change")
        if isinstance(change, dict):
            event.project_name = change.get("project")
            event.branch = change.get("branch")
            change_number = change.get("number")
            if change_number is not None:
                event.change_number = str(change_number)

        patchset = data.get("patchSet")
        if isinstance(patchset, dict):
            patch_number = patchset.get("number")
            if patch_number is not None:
                event.patch_number = str(patch_number)

        refupdate = data.get("refUpdate")
        if isinstance(refupdate, dict):
            event.project_name = refupdate.get("project", event.project_name)
            event.ref = refupdate.get("refName")
            event.oldrev = refupdate.get("oldRev")
            event.newrev = refupdate.get("newRev")

        return event

    def _handle_event(self, data: dict[str, Any]) -> tuple[bool , dict[str , Any]]:
        event = self._build_event(data)

        if event.change_number:
            try:
                event.change_details = self.connection.getChange(event.change_number)
            except Exception as exc:
                self.logger.error("Failed to enrich Gerrit event for change %s: %s", event.change_number, exc, exc_info=True)
                return False

        return True , event

    def run(self) -> None:
        while not self._stopped:
            data: Optional[dict[str, Any]] = None
            try:
                data = self.kafka_connection.getEvent(timeout=1.0)

                handled , data = self._handle_event(data)
                if handled:
                    self.sched.addEvent(event)
                self.kafka_connection.addEvent(data)
            except Empty:
                continue
            except Exception:
                self.kafka_connection.eventDone()
            finally:
                self.kafka_connection.eventDone()

class GerritRestConnection(BaseConnection):
    """REST client for querying Gerrit changes."""
    logger = get_logger("torri.connection.gerrit")
    GERRIT_CHANGE_CACHE_SIZE = 10_000

    def __init__(self, base_url: str, auth: Optional[tuple[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._authenticated = auth is not None
        if auth:
            self.session.auth = auth
        self.change_cache_rest_api = LRUCache(maxsize=self.GERRIT_CHANGE_CACHE_SIZE)
        self.cache_lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=5)

    def query(self, change_id: int | str) -> dict:
        """
        Query a Gerrit change by number or Change-Id.
        Returns the full change detail including labels, messages, and current revision.
        """
        endpoint = f"/changes/{change_id}/detail"
        data = self._get(endpoint)
        self.logger.debug("Queried change %s, status: %s", change_id, data.get("status"))
        return data

    # --- private helpers ---

    def _get(self, endpoint: str) -> dict:
        url = self._build_url(endpoint)
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        return self._parse_response(response.text)

    def _build_url(self, endpoint: str) -> str:
        if self._authenticated:
            return f"{self.base_url}/a{endpoint}"
        return f"{self.base_url}{endpoint}"

    def _parse_response(self, text: str) -> dict:
        # Gerrit prefixes JSON responses with )]}' to prevent XSSI
        if text.startswith(")]}'"):
            text = text[4:]
        return json.loads(text)
    def _getChange():
        
    def addChangeToCache(self, key, value):
        with self.cache_lock:
            if key in self.change_cache_rest_api.keys():
                return self.change_cache_rest_api[key]
            self.change_cache_rest_api[key] = value
            return value

    def getChangeFromCache(self, key):
        with self.cache_lock:
            if key in self.change_cache_rest_api.keys():
                return self.change_cache_rest_api[key]
        return None

