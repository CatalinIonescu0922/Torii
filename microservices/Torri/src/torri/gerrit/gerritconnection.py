import json
import os
import requests
import threading
from shared.logger_setup import get_logger
from shared.exceptions import GerritQueryError
from queue import Empty
from shared.gerritmodel import GerritChange, GerritTriggerEvent
from torri.connection import BaseConnection
from shared.gerritmodel import known_events
from concurrent.futures import ThreadPoolExecutor
from torri.kafka.producer import KafkaProducerClient


class GerritEventProcessor(threading.Thread):
    def __init__(self, kafka_connection, gerrit_connection):
        super().__init__(name="GerritEventProcessor", daemon=True)
        self.logger = get_logger("torri.gerrit.event_processor")
        self.kafka_connection = kafka_connection
        self.gerrit_connection = gerrit_connection
        self._stopped = False
        self._trigger_topic = os.getenv("KAFKA_TRIGGER_TOPIC", "trigger-events")
        self._producer = KafkaProducerClient()

    def stop(self) -> None:
        self._stopped = True
        self.kafka_connection.addEvent(None)

    def _build_event(self, data):
        self.logger.debug("Building event from payload keys=%s", list(data.keys()))
        event = GerritTriggerEvent()
        event.type = str(data.get("type", "unknown"))
        if event.type not in known_events:
            self.logger.debug("Skip unknown event type=%s", event.type)
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
            patchset_ref = patchset.get("ref")
            if patchset_ref:
                event.ref = str(patchset_ref)

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
            self.kafka_connection.eventDone()
            return

        self.logger.debug(
            "Handling event type=%s change=%s patch=%s project=%s",
            event.type,
            event.change_number,
            event.patch_number,
            event.project_name,
        )

        if event.change_number:
            self.logger.debug("Submitting change enrichment for change=%s", event.change_number)
            future = self.gerrit_connection.executor.submit(
                self.gerrit_connection.getChange, event.change_number
            )
            future.add_done_callback(lambda f: self._on_enrichment_done(f, event))
        else:
            self.logger.debug("Event has no change number, dispatching directly")
            self._dispatch_event(event)
            self.kafka_connection.eventDone()

    def _on_enrichment_done(self, future, event):
        try:
            # result is a GerritChange now stored in gerrit_conn's LRU cache.
            # The scheduler will fetch it from there — no need to ship it through Kafka.
            future.result()
            self.logger.debug("Enrichment done for change=%s", event.change_number)
            self._dispatch_event(event)
        except Exception as exc:
            self.logger.error(
                "Failed to enrich event for change %s: %s",
                event.change_number, exc, exc_info=True
            )
        finally:
            self.kafka_connection.eventDone()

    def _dispatch_event(self, event):
        self.logger.debug(
            "Dispatch event type=%s change=%s branch=%s",
            event.type,
            event.change_number,
            event.branch,
        )
        key = event.project_name or event.change_number or "unknown"
        self._producer.send_message(self._trigger_topic, key, event.to_dict())
        self._producer.flush()
        self.logger.info(
            "Published trigger event type=%s change=%s to topic=%s",
            event.type, event.change_number, self._trigger_topic,
        )

    def run(self) -> None:
        while not self._stopped:
            try:
                data = self.kafka_connection.getEvent(timeout=1.0)
                if data is None:
                    continue
                self._handle_event(data)
            except Empty:
                continue
            except Exception:
                self.logger.exception("Unexpected error in event loop")
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

    def __init__(self, base_url, auth=None, redis=None):
        self.logger = get_logger("torri.connection.gerrit")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._authenticated = auth is not None
        if auth:
            self.session.auth = auth
        self.redis = redis
        self._network_manager = ChangeNetworkManager()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.logger.debug(
            "Initialized GerritRestConnection base_url=%s authenticated=%s",
            self.base_url,
            self._authenticated,
        )

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
                self.logger.debug(
                    "Query change=%s attempt=%s/%s",
                    change_number,
                    attempt + 1,
                    number_of_retries,
                )
                data = self._get(endpoint)
                related = self._get('changes/%s/revisions/%s/related' % (
                    change_number, data['current_revision']))
                self.logger.debug(
                    "Query success change=%s current_revision=%s related_count=%s",
                    change_number,
                    data.get('current_revision'),
                    len(related.get('changes', [])) if isinstance(related, dict) else 0,
                )
                return data, related
            except Exception as e:
                if attempt < number_of_retries - 1:
                    self.logger.info(f"Querying gerrit failed on attempt {attempt + 1}, retrying...")
                    continue
                raise GerritQueryError(f"Failed to query Gerrit change {change_number}") from e

    def getChange(self, change_number, change_patchset=None, refresh=False, history=None):
        return self._getChange(change_number, change_patchset, refresh, history)

    def submit_change(self, change_number: str, strategy: str = None) -> tuple:
        """
        Submit (merge) a change to Gerrit.
        
        Endpoint: POST /a/changes/{change-id}/submit
        
        If strategy is None, Gerrit uses the repo's default strategy
        configured in gerrit.config
        
        Args:
            change_number: Change ID or number
            strategy: Optional merge strategy override
        
        Returns:
            (success: bool, response: dict or error_msg: str)
        """
        try:
            endpoint = f'changes/{change_number}/submit'
            payload = {}
            
            if strategy:
                payload['strategy'] = strategy
            
            # Empty payload = use repo's default strategy
            response = self._post(endpoint, payload if payload else None)
            
            status = response.get('status')  # MERGED, ABANDONED, etc.
            self.logger.info(
                "Submitted change %s, status=%s",
                change_number, status
            )
            
            return True, response
        
        except Exception as e:
            error_msg = str(e)
            self.logger.error("Failed to submit change %s: %s", change_number, error_msg)
            return False, error_msg
    
    def mergeable(self, change_number: str) -> tuple:
        """
        Check if a change is currently mergeable.
        
        Returns:
            (mergeable: bool, status_dict)
        """
        try:
            endpoint = f'changes/{change_number}/merge'
            response = self._get(endpoint)
            
            mergeable = response.get('mergeable', False)
            self.logger.debug(
                "Change %s mergeable=%s conflict=%s",
                change_number,
                mergeable,
                response.get('merge_conflict', False)
            )
            
            return mergeable, response
        
        except Exception as e:
            self.logger.warning("Error checking mergeable status: %s", e)
            return False, str(e)
    
    def set_review(self, change_number: str, patchset: str, message: str, labels: dict = None) -> bool:
        """
        Post a review/vote on a change.
        
        Args:
            change_number: Change ID
            patchset: Patchset number
            message: Review message
            labels: Dict of label votes, e.g., {"Code-Review": 1, "Verified": 1}
        
        Returns:
            success: bool
        """
        try:
            endpoint = f'changes/{change_number}/revisions/{patchset}/review'
            payload = {
                'message': message,
                'labels': labels or {}
            }
            
            self._post(endpoint, payload)
            
            self.logger.info(
                "Posted review on change %s patchset %s",
                change_number, patchset
            )
            return True
        
        except Exception as e:
            self.logger.error("Error posting review: %s", e)
            return False

    # --- helpers ---

    def _get(self, endpoint):
        url = self._build_url(endpoint)
        self.logger.debug("HTTP GET %s", url)
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        self.logger.debug("HTTP %s bytes=%s", response.status_code, len(response.text))
        return self._parse_response(response.text)

    def _post(self, endpoint, payload=None):
        """POST request to Gerrit API."""
        url = self._build_url(endpoint)
        self.logger.debug("HTTP POST %s payload=%s", url, payload)
        response = self.session.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        response.raise_for_status()
        self.logger.debug("HTTP %s bytes=%s", response.status_code, len(response.text))
        return self._parse_response(response.text)

    def _put(self, endpoint, payload=None):
        """PUT request to Gerrit API."""
        url = self._build_url(endpoint)
        self.logger.debug("HTTP PUT %s payload=%s", url, payload)
        response = self.session.put(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        response.raise_for_status()
        self.logger.debug("HTTP %s bytes=%s", response.status_code, len(response.text))
        return self._parse_response(response.text)

    def _build_url(self, endpoint):
        endpoint = endpoint.lstrip("/")
        if self._authenticated:
            return f"{self.base_url}/a/{endpoint}"
        return f"{self.base_url}/{endpoint}"

    def _parse_response(self, text):
        # Gerrit prefixes JSON responses with )]}' to prevent XSSI
        if text.startswith(")]}'"):
            text = text[4:]
        return json.loads(text)

    def _getChange(self, change_number, change_patchset=None, refresh=False, history=None):
        if not refresh and self.redis:
            change = self.redis.get_change(change_number, change_patchset)
            if change:
                self.logger.debug("Redis hit for change=%s patchset=%s", change_number, change_patchset)
                return change

        self.logger.debug("Redis miss for change=%s patchset=%s refresh=%s", change_number, change_patchset, refresh)

        should_fetch, payload = self._network_manager.begin(str(change_number))
        self.logger.debug("Network manager state=%s change=%s", should_fetch, change_number)
        if should_fetch == 'inflight':
            self.logger.warning("Circular dependency on change %s, returning in-flight object.", change_number)
            return payload or GerritChange()
        if should_fetch == 'wait':
            self.logger.debug("Waiting for in-flight fetch on change=%s", change_number)
            payload.wait()
            self._network_manager.end_wait()
            if self.redis:
                change = self.redis.get_change(change_number, change_patchset)
                if change:
                    return change
            return GerritChange()

        # should_fetch == 'fetch'
        try:
            change = GerritChange()
            self._network_manager.register(str(change_number), change)
            self.logger.debug("Fetching and updating change=%s patchset=%s", change_number, change_patchset)
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
        self.logger.debug(
            "Dependencies for change=%s depends_on=%s needed_by=%s",
            change_number,
            depends_on,
            needed_by_changes,
        )
        return depends_on, needed_by_changes

    def _updateChange(self, change, change_number, change_patchset, history=None):
        if history is None:
            history = []
        history = history + [str(change_number)]
        self.logger.debug(
            "Updating change=%s patchset=%s history=%s",
            change_number,
            change_patchset,
            history,
        )

        data, related = self.query(change_number)
        change.update(data)

        dependency_number = int(change_number)

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

        if self.redis:
            self.redis.store_change(change.number, change.patchset, change)
        self.logger.debug(
            "Updated change=%s needs=%s needed_by=%s",
            change_number,
            len(change.needs_changes),
            len(change.needed_by_changes),
        )

        return change

