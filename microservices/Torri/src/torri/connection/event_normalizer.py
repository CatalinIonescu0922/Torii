"""
Event normalization interface.

All connections normalize raw events from their source (Kafka for Gerrit, webhooks for GitHub, etc.)
to a unified internal format. This abstraction allows different sources to be added without
modifying core scheduler code.

Design Pattern: Adapter Pattern + Strategy Pattern
- Each connection has its own EventNormalizer strategy
- Normalizers convert source-specific events to internal TriggerEvent format
- Scheduler works with normalized events only (source-agnostic)
"""

import abc
from typing import Dict, Any, Optional, Tuple


class EventNormalizer(metaclass=abc.ABCMeta):
    """
    Abstract interface for normalizing raw events to internal format.
    
    Different VCS sources produce different event formats:
    - Gerrit: Kafka JSON with patchSet, change objects
    - GitHub: Webhook JSON with pull_request, repository objects
    - GitLab: Webhook JSON with object_kind, merge_request objects
    
    Each connection implements EventNormalizer to convert its format to unified TriggerEvent.
    """
    
    @abc.abstractmethod
    def can_normalize(self, event_data: Dict[str, Any]) -> bool:
        """
        Check if this normalizer can handle the given event.
        
        Args:
            event_data: Raw event data from source
        
        Returns:
            bool: True if this normalizer handles this event type
            
        Example:
            - GerritEventNormalizer: checks if 'type' in event_data and event_type is known
            - GitHubEventNormalizer: checks if 'pull_request' in event_data
            - GitLabEventNormalizer: checks if 'object_kind' == 'merge_request'
        """
        pass
    
    @abc.abstractmethod
    def normalize(self, event_data: Dict[str, Any]) -> Optional['TriggerEvent']:
        """
        Normalize raw event to internal TriggerEvent format.
        
        Args:
            event_data: Raw event from VCS source
        
        Returns:
            TriggerEvent: Normalized event, or None if event should be ignored
            
        The returned TriggerEvent should contain:
        - source: str (gerrit, github, gitlab, bitbucket, etc.)
        - type: str (patchset-created, pull-request-opened, merge-request-opened, etc.)
        - project_name: str
        - branch: str
        - change_number / pr_number / mr_number: str (unique identifier)
        - author: str
        - ref: str (git ref)
        - commit_sha: str
        
        Implementation should:
        1. Extract relevant fields from source-specific format
        2. Map source-specific action names to internal format
        3. Handle optional/missing fields gracefully
        4. Return None if event should be ignored (e.g., draft changes)
        """
        pass
    
    @abc.abstractmethod
    def get_source_name(self) -> str:
        """
        Get the name of the VCS source this normalizer handles.
        
        Returns:
            str: 'gerrit', 'github', 'gitlab', etc.
            
        Used for logging, routing, and identifying event origin.
        """
        pass


class TriggerEvent:
    """
    Unified internal event representation.
    
    All trigger events, regardless of source, are normalized to this format.
    Scheduler works exclusively with this format (source-agnostic).
    """
    
    def __init__(self):
        # Source identification
        self.source = None  # 'gerrit', 'github', 'gitlab', etc.
        self.connection_name = None  # Name of connection this came from
        
        # Event type (normalized)
        self.type = None  # 'patchset-created', 'pull-request-opened', etc.
        
        # Project identification
        self.project_name = None
        self.branch = None
        self.repository = None
        
        # Change identification (varies by source)
        self.change_id = None  # Unique ID: 'gerrit:project/123', 'github:org/repo/456', etc.
        self.change_number = None  # Gerrit change number (str)
        self.pr_number = None  # GitHub/GitLab PR/MR number (str)
        
        # Revision identification
        self.patchset = None  # Gerrit patchset number (str)
        self.commit_sha = None  # Commit hash
        self.ref = None  # Full git ref
        
        # Author information
        self.author = None
        self.author_email = None
        
        # Additional metadata
        self.message = None
        self.comment = None
        
        # Enriched data (filled later by connection)
        self.change_details = None  # Full change object with labels, reviews, etc.
        
        # Raw event (for debugging)
        self.raw_event = None
    
    def __repr__(self):
        return (f'<TriggerEvent source={self.source} type={self.type} '
                f'project={self.project_name} branch={self.branch} '
                f'change_id={self.change_id}>')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            'source': self.source,
            'connection_name': self.connection_name,
            'type': self.type,
            'project_name': self.project_name,
            'branch': self.branch,
            'change_id': self.change_id,
            'change_number': self.change_number,
            'pr_number': self.pr_number,
            'patchset': self.patchset,
            'commit_sha': self.commit_sha,
            'ref': self.ref,
            'author': self.author,
            'author_email': self.author_email,
            'message': self.message,
            'comment': self.comment,
        }


class EnrichmentError(Exception):
    """Raised when event enrichment fails."""
    pass


class EventEnricher(metaclass=abc.ABCMeta):
    """
    Abstract interface for enriching events with additional data.
    
    After normalization, events can be enriched with full change details:
    - Gerrit: Get full change with labels, reviewers, messages
    - GitHub: Get PR with statuses, reviews, files changed
    - GitLab: Get MR with discussions, approvals, diffs
    """
    
    @abc.abstractmethod
    def enrich(self, event: TriggerEvent) -> bool:
        """
        Enrich event with full details from VCS API.
        
        Args:
            event: TriggerEvent to enrich (modified in-place)
        
        Returns:
            bool: True if enrichment succeeded, False if failed
            
        Should populate event.change_details with:
        - Full change/PR/MR object
        - Reviews and approvals
        - Labels and metadata
        - Files changed
        - Comments/discussions
        
        Implementation notes:
        - Should handle network errors gracefully
        - Can return False to skip enrichment (event still processed)
        - Some sources may not require enrichment
        """
        pass
