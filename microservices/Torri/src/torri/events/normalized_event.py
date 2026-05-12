"""
Normalized internal event representation.

All VCS events (Gerrit, GitHub, GitLab) normalize to this format.
Scheduler works only with NormalizedEvent, never sees source-specific formats.
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


class EventType(Enum):
    """Normalized event types across all VCS systems."""
    PATCHSET_CREATED = "patchset_created"        # Gerrit
    PULL_REQUEST_OPENED = "pull_request_opened"   # GitHub
    MERGE_REQUEST_OPENED = "merge_request_opened" # GitLab
    # Common events
    CHANGE_UPDATED = "change_updated"
    CHANGE_MERGED = "change_merged"
    CHANGE_ABANDONED = "change_abandoned"


@dataclass
class NormalizedEvent:
    """
    Internal event format - connection-agnostic.
    
    All VCS connections normalize their events to this format.
    Scheduler processes only this format, never sees Gerrit/GitHub/GitLab specifics.
    """
    
    # Event identification
    event_id: str                              # Unique event ID
    event_type: EventType                      # Normalized event type
    source: str                                # Connection source: 'gerrit', 'github', 'gitlab'
    source_event_time: int                     # Timestamp from source
    
    # Change identification  
    change_id: str                             # Unique change ID (includes project, number, patchset)
    change_number: str                         # Source-specific change number
    patchset_number: Optional[str] = None      # For multi-revision systems
    
    # Repository info
    project: str                               # Project/repository name
    branch: str                                # Target branch
    
    # Commit info
    commit_sha: str = ""                       # Commit hash
    
    # Author info
    author_name: str = ""                      # Submitter name
    author_email: str = ""                     # Submitter email
    author_username: str = ""                  # Username in VCS system
    
    # Change metadata
    title: str = ""                            # Change/PR title
    description: str = ""                      # Change/PR description
    
    # Source-specific metadata (preserved for connection callbacks)
    source_data: Dict[str, Any] = None         # Raw source event (for debugging, fallback)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict, handling non-serializable types."""
        data = asdict(self)
        data['event_type'] = self.event_type.value
        return data
    
    def __repr__(self) -> str:
        """Human-readable representation."""
        return (f"NormalizedEvent(source={self.source}, change_id={self.change_id}, "
                f"event_type={self.event_type.name}, project={self.project}, branch={self.branch})")
