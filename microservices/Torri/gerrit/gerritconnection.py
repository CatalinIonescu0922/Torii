import json
import requests
import threading
from cachetools import LRUCache
from shared.logger_setup import get_logger
from shared.exceptions import GerritQueryError
from queue import Empty
from shared.gerritmodel import GerritChange, GerritTriggerEvent
from connection import BaseConnection
from shared.gerritmodel import known_events
from concurrent.futures import ThreadPoolExecutor


class GerritEventProcessor(threading.Thread):
    logger = get_logger("torri.gerrit.event_processor")
    def __init__(self, kafka_connection, gerrit_connection):
        super().__init__(name="GerritEventProcessor", daemon=True)
        self.kafka_connection = kafka_connection
        self.gerrit_connection = gerrit_connection
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        self.kafka_connection.addEvent(None)

    def _build_event(self, data):
        event = GerritTriggerEvent()
        event.type = str(data.get("type", "unknown"))
        if event.type not in known_events:
            self.logger.debug("Skip unknown event")
            return None
        event.comment = str(data.get("comment", ""))

        change = data.get("change")
        if isinstance(change, dict):
            event.project_name = str(change.get("project") or "")
            event.branch = str(change.get("branch") or "")
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
            event.project_name = str(refupdate.get("project") or event.project_name)
            event.ref = str(refupdate.get("refName") or "")
            event.oldrev = str(refupdate.get("oldRev") or "")
            event.newrev = str(refupdate.get("newRev") or "")

        return event

    def _handle_event(self, data):
        event = self._build_event(data)
        if event is None:
            return False, None

        if event.change_number:
            try:
                event.change_details = self.gerrit_connection.getChange(event.change_number)
            except Exception as exc:
                self.logger.error("Failed to enrich Gerrit event for change %s: %s", event.change_number, exc, exc_info=True)
                return False, None

        return True, event

    def run(self) -> None:
        while not self._stopped:
            data = None
            try:
                data = self.kafka_connection.getEvent(timeout=1.0)

                handled, event = self._handle_event(data)
                if handled:
                    self.gerrit_connection.sched.addEvent(event)
                self.kafka_connection.addEvent(event)
            except Empty:
                continue
            except Exception:
                self.kafka_connection.eventDone()
            finally:
                self.kafka_connection.eventDone()

class ChangeNetworkManager:
    """Ensures only one thread fetches a given change over the network at a time.

    Tracks a wait graph to detect circular dependencies before blocking.
    Stores the in-flight GerritChange object so same-thread re-entry (via
    needs_changes / needed_by_changes resolution) returns the partial object
    immediately instead of deadlocking.
    """

    def __init__(self):
        self._active = {}   # change_number -> (Event, owner_thread_id, GerritChange | None)
        self._waiting = {}  # thread_id -> change_number it is blocked on
        self._lock = threading.Lock()

    def begin(self, change_number):
        """
        Returns ('fetch', None)      — this thread should go to the network.
        Returns ('wait', event)      — another thread is fetching; caller should block.
        Returns ('inflight', obj)    — same-thread re-entry or cross-thread cycle;
                                       return the partial GerritChange immediately.
        """
        tid = threading.current_thread().ident
        with self._lock:
            if change_number not in self._active:
                self._active[change_number] = (threading.Event(), tid, None)
                return 'fetch', None
            event, owner, inflight = self._active[change_number]
            if owner == tid:
                return 'inflight', inflight
            self._waiting[tid] = change_number
            if self._has_cycle(change_number, tid):
                del self._waiting[tid]
                return 'inflight', inflight
            return 'wait', event

    def register(self, change_number, change_obj):
        with self._lock:
            if change_number in self._active:
                event, tid, _ = self._active[change_number]
                self._active[change_number] = (event, tid, change_obj)

    def end_wait(self):
        tid = threading.current_thread().ident
        with self._lock:
            self._waiting.pop(tid, None)

    def finish(self, change_number):
        with self._lock:
            entry = self._active.pop(change_number, None)
        if entry:
            event, _, _ = entry
            event.set()

    def _has_cycle(self, start_change, requesting_tid):
        visited = set()
        current = start_change
        while True:
            if current in visited:
                return True
            visited.add(current)
            entry = self._active.get(current)
            if entry is None:
                return False
            _, owner, _ = entry
            if owner == requesting_tid:
                return True
            current = self._waiting.get(owner)
            if current is None:
                return False


class GerritRestConnection(BaseConnection):
    """REST client for querying Gerrit changes."""
    logger = get_logger("torri.connection.gerrit")
    GERRIT_CHANGE_CACHE_SIZE = 10_000

    def __init__(self, base_url, auth=None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._authenticated = auth is not None
        if auth:
            self.session.auth = auth
        self.change_cache_rest_api = LRUCache(maxsize=self.GERRIT_CHANGE_CACHE_SIZE)
        self.cache_lock = threading.RLock()
        self._network_manager = ChangeNetworkManager()
        self.executor = ThreadPoolExecutor(max_workers=5)

    def query(self, change_number):
        """
        Query a Gerrit change by number or Change-Id.
        Returns the full change detail including labels, messages, and current revision.
        """
        endpoint = ('changes/%s?o=DETAILED_ACCOUNTS&o=CURRENT_REVISION&'
            'o=CURRENT_COMMIT&o=CURRENT_FILES&o=LABELS&'
            'o=DETAILED_LABELS&o=ALL_REVISIONS' % (change_number,))
        number_of_retries = 3
        for attempt in range(number_of_retries):
            try:
                data = self._get(endpoint)
                related = self._get('changes/%s/revisions/%s/related' % (
                    change_number, data['current_revision']))
                return data, related
            except Exception as e:
                if attempt < number_of_retries - 1:
                    self.logger.info(f"Querying gerrit failed on attempt {attempt + 1}, retrying...")
                    continue
                raise GerritQueryError(f"Failed to query Gerrit change {change_number}") from e

    # --- private helpers ---

    def _get(self, endpoint):
        url = self._build_url(endpoint)
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        return self._parse_response(response.text)

    def _build_url(self, endpoint):
        if self._authenticated:
            return f"{self.base_url}/a/{endpoint}"
        return f"{self.base_url}{endpoint}"

    def _parse_response(self, text):
        # Gerrit prefixes JSON responses with )]}' to prevent XSSI
        if text.startswith(")]}'"):
            text = text[4:]
        return json.loads(text)

    def _change_key(self, change_number, change_patchset=None):
        return (str(change_number), None if change_patchset is None else str(change_patchset))

    def _getChange(self, change_number, change_patchset=None, refresh=False, history=None):
        key = self._change_key(change_number, change_patchset)

        change = self.getChangeFromCache(key)
        if change is not None and not refresh:
            return change

        should_fetch, payload = self._network_manager.begin(str(change_number))
        if should_fetch == 'inflight':
            self.logger.warning("Circular dependency on change %s, returning in-flight object.", change_number)
            return payload or self.getChangeFromCache(key)
        if should_fetch == 'wait':
            payload.wait()
            self._network_manager.end_wait()
            return self.getChangeFromCache(key)

        # should_fetch == 'fetch'
        try:
            change = self.getChangeFromCache(key)
            if change is not None and not refresh:
                return change

            if change is None:
                change = GerritChange()
                self.addChangeToCache(key, change)

            self._network_manager.register(str(change_number), change)
            return self._updateChange(change, change_number, change_patchset, history=history)
        finally:
            self._network_manager.finish(str(change_number))

    def _prepareDependencyListFromHttp(self, related, current_revision, change_number):
        depends_on = None
        needed_by_changes = []
        for change in related["changes"]:
            if change["commit"]["commit"] == current_revision:
                parent = change["commit"]["parents"][0]["commit"]
                for change in related["changes"]:
                    if change["commit"]["commit"] == parent:
                        depends_on = (change["_change_number"], change["_current_revision_number"])
                    elif change["_change_number"] > change_number:
                        needed_by_changes.append((change["_change_number"], change["_current_revision_number"]))
        return depends_on, needed_by_changes

    def _updateChange(self, change, change_number, change_patchset, history=None):
        if history is None:
            history = []
        history = history + [str(change_number)]

        data, related = self.query(change_number)
        change.update(data)

        try:
            dependency_number = int(change_number)
        except (TypeError, ValueError):
            dependency_number = change_number

        depends_on, needed_by = self._prepareDependencyListFromHttp(
            related, data.get("current_revision"), dependency_number
        )

        change.needs_changes = []
        if depends_on:
            dep_num, dep_patchset = depends_on
            if str(dep_num) not in history:
                change.needs_changes = [self._getChange(dep_num, dep_patchset, history=history)]

        change.needed_by_changes = []
        for nb_num, nb_patchset in needed_by:
            if str(nb_num) not in history:
                change.needed_by_changes.append(self._getChange(nb_num, nb_patchset, history=history))

        with self.cache_lock:
            self.change_cache_rest_api[self._change_key(change_number, change_patchset)] = change

        return change

    def addChangeToCache(self, key, value):
        with self.cache_lock:
            if key in self.change_cache_rest_api:
                return self.change_cache_rest_api[key]
            self.change_cache_rest_api[key] = value
            return value

    def getChangeFromCache(self, key):
        with self.cache_lock:
            if key in self.change_cache_rest_api:
                return self.change_cache_rest_api[key]
        return None
