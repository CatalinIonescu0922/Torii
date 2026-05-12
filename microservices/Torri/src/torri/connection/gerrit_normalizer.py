"""
Gerrit event normalization implementation.

Converts Gerrit Kafka events to unified internal TriggerEvent format.
"""

from typing import Dict, Any, Optional
from shared.logger_setup import get_logger
from shared.gerritmodel import known_events
from torri.connection.event_normalizer import (
    EventNormalizer,
    TriggerEvent,
    EventEnricher,
    EnrichmentError,
)


class GerritEventNormalizer(EventNormalizer):
    """
    Normalize Gerrit events from Kafka to internal TriggerEvent format.
    
    Gerrit event structure (from Kafka):
    {
        "type": "patchset-created",
        "change": {"number": 123, "project": "repo", "branch": "main"},
        "patchSet": {"number": 1, "revision": "abc123..."},
        "refUpdate": {"refName": "refs/...", "oldRev": "...", "newRev": "..."},
        ...
    }
    """
    
    def __init__(self):
        self.logger = get_logger('torri.connection.gerrit_normalizer')
    
    def can_normalize(self, event_data: Dict[str, Any]) -> bool:
        """
        Check if this is a valid Gerrit event.
        
        Gerrit events have 'type' field and should be in known_events list.
        """
        if not isinstance(event_data, dict):
            return False
        
        event_type = event_data.get('type')
        return event_type is not None and event_type in known_events
    
    def normalize(self, event_data: Dict[str, Any]) -> Optional[TriggerEvent]:
        """
        Normalize Gerrit Kafka event to TriggerEvent.
        
        Returns None if event should be skipped (e.g., unknown type).
        """
        try:
            # Check event type
            event_type = event_data.get('type')
            if not event_type or event_type not in known_events:
                self.logger.debug(f"Skipping unknown event type: {event_type}")
                return None
            
            # Create event
            event = TriggerEvent()
            event.source = 'gerrit'
            event.connection_name = event_data.get('connection_name', 'gerrit')
            event.type = event_type
            event.comment = str(event_data.get('comment', ''))
            event.raw_event = event_data
            
            # Extract change information
            change = event_data.get('change', {})
            if isinstance(change, dict):
                event.project_name = str(change.get('project') or '')
                event.branch = str(change.get('branch') or '')
                change_number = change.get('number')
                if change_number is not None:
                    event.change_number = str(change_number)
                    event.change_id = f"gerrit:{event.project_name}/{change_number}"
                
                author = change.get('owner', {})
                if isinstance(author, dict):
                    event.author = str(author.get('name') or '')
                    event.author_email = str(author.get('email') or '')
            
            # Extract patchset information
            patchset = event_data.get('patchSet', {})
            if isinstance(patchset, dict):
                patch_number = patchset.get('number')
                if patch_number is not None:
                    event.patchset = str(patch_number)
                
                revision = patchset.get('revision')
                if revision:
                    event.commit_sha = revision
                    # Build Gerrit synthetic ref
                    if event.change_number:
                        change_num = int(event.change_number)
                        last_two = change_num % 100
                        event.ref = f"refs/changes/{last_two:02d}/{change_num}/{patch_number}"
            
            # Extract ref update information (for ref-updated events)
            refupdate = event_data.get('refUpdate', {})
            if isinstance(refupdate, dict):
                # May override project/branch for ref-updated events
                if not event.project_name:
                    event.project_name = str(refupdate.get('project') or '')
                
                event.ref = str(refupdate.get('refName') or event.ref or '')
                
                newrev = refupdate.get('newRev')
                if newrev and not event.commit_sha:
                    event.commit_sha = newrev
            
            self.logger.debug(
                f"Normalized Gerrit event: type={event.type} change={event.change_number} "
                f"patchset={event.patchset} project={event.project_name} branch={event.branch}"
            )
            
            return event
        
        except Exception as e:
            self.logger.error(f"Failed to normalize Gerrit event: {e}", exc_info=True)
            return None
    
    def get_source_name(self) -> str:
        """Return source name."""
        return 'gerrit'


class GerritEventEnricher(EventEnricher):
    """
    Enrich Gerrit events with full change details from API.
    
    Fetches:
    - Full change object with labels
    - All reviews and votes
    - Patch details
    - Related changes
    """
    
    def __init__(self, gerrit_connection):
        """
        Initialize with Gerrit REST connection.
        
        Args:
            gerrit_connection: GerritRestConnection instance
        """
        self.gerrit_connection = gerrit_connection
        self.logger = get_logger('torri.connection.gerrit_enricher')
    
    def enrich(self, event: TriggerEvent) -> bool:
        """
        Fetch full change details from Gerrit API.
        
        Populates event.change_details with full change object.
        """
        if not event.change_number:
            self.logger.debug("Event has no change number, skipping enrichment")
            return True  # Not an error, just skip
        
        try:
            self.logger.debug(f"Enriching Gerrit change {event.change_number}")
            
            # Use getChange to fetch full details
            change_details = self.gerrit_connection.getChange(event.change_number)
            event.change_details = change_details
            
            self.logger.debug(f"Successfully enriched change {event.change_number}")
            return True
        
        except Exception as e:
            self.logger.warning(
                f"Failed to enrich Gerrit change {event.change_number}: {e}",
                exc_info=True
            )
            # Enrichment failure is not fatal - event still processed
            return False
