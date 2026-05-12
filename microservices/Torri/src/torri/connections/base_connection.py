"""
Base connection abstraction for VCS event sources.

All source connections (Gerrit, GitHub, GitLab, Bitbucket) inherit this interface.
Connections normalize source-specific events to internal NormalizedEvent format.

Design Principle: Open/Closed - add new sources without modifying scheduler.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, List
from torri.events import NormalizedEvent


class Connection(ABC):
    """
    Abstract base for VCS event source connections.
    
    Responsibilities:
    1. Receive events from source (webhook, polling, message queue)
    2. Normalize to internal NormalizedEvent format
    3. Report back to source (status, comments, merge decisions)
    4. Manage source-specific details (auth, API endpoints, etc.)
    """
    
    @abstractmethod
    def get_connection_name(self) -> str:
        """
        Get unique connection identifier.
        
        Returns:
            Connection name (e.g., 'gerrit-main', 'github-public', 'gitlab-internal')
        """
        pass
    
    @abstractmethod
    def get_source_type(self) -> str:
        """
        Get source type identifier.
        
        Returns:
            VCS type: 'gerrit', 'github', 'gitlab', 'bitbucket', etc.
        """
        pass
    
    @abstractmethod
    def normalize_event(self, raw_event: Dict[str, Any]) -> Tuple[bool, Optional[NormalizedEvent]]:
        """
        Parse and normalize source-specific event to internal format.
        
        Each VCS produces different event formats. This converts to unified NormalizedEvent.
        
        Args:
            raw_event: Raw event from source (Kafka message, webhook JSON, API response)
        
        Returns:
            (success: bool, normalized_event: NormalizedEvent or None)
            
        Example (Gerrit event):
            {
                "type": "patchset-created",
                "change": {"number": 123, "project": "my-project", "branch": "main"},
                "patchSet": {"number": 1, "revision": "abc123"},
                "uploader": {"name": "Alice", "email": "alice@example.com"}
            }
            ↓
            NormalizedEvent(
                source='gerrit',
                event_type=EventType.PATCHSET_CREATED,
                change_id='gerrit:my-project/123/1',
                change_number='123',
                patchset_number='1',
                ...
            )
        """
        pass
    
    @abstractmethod
    def get_change_details(self, change_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Retrieve full change details from source API.
        
        Used by scheduler to get additional change metadata.
        
        Args:
            change_id: Normalized change ID (e.g., 'gerrit:project/123/1')
        
        Returns:
            (success: bool, details: Dict with change metadata)
        """
        pass
    
    @abstractmethod
    def report_status(
        self,
        change_id: str,
        status: str,
        message: str,
        details_url: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Report pipeline status back to source (comment, check, label, etc.).
        
        Allow developers to see CI results in their VCS UI.
        
        Args:
            change_id: Normalized change ID
            status: Status string ('PASSED', 'FAILED', 'PENDING')
            message: Human-readable status message
            details_url: Optional link to detailed results
        
        Returns:
            (success: bool, response: str or error message)
            
        Examples:
        - Gerrit: Post comment via API or SSH
        - GitHub: Create check run or set status
        - GitLab: Create note on MR or set pipeline status
        """
        pass
    
    @abstractmethod
    def merge_change(self, change_id: str) -> Tuple[bool, str]:
        """
        Merge/submit change in source after all gates pass.
        
        Args:
            change_id: Normalized change ID
        
        Returns:
            (success: bool, response: str with merge result or error)
            
        Examples:
        - Gerrit: Submit via /changes/{id}/submit
        - GitHub: Merge PR via /repos/{owner}/{repo}/pulls/{pr}/merge
        - GitLab: Merge MR via /projects/{id}/merge_requests/{mr}/merge
        """
        pass
    
    @abstractmethod
    def create_synthetic_ref(self, change_id: str) -> Tuple[bool, str]:
        """
        Create synthetic ref for pre-merge testing.
        
        Allows testing changes as if merged (before actual merge).
        E.g., create merge-base commit, tag it, run tests against it.
        
        Args:
            change_id: Normalized change ID
        
        Returns:
            (success: bool, synthetic_ref: str or error message)
            
        Examples:
        - Gerrit: "refs/changes/45/12345/1"
        - GitHub: "refs/pull/789/merge"
        - Custom: "refs/synthetic/github/org/repo/789"
        """
        pass
    
    @abstractmethod
    def verify_authentication(self) -> Tuple[bool, str]:
        """
        Verify connection can authenticate to source.
        
        Called during startup to validate credentials/tokens.
        
        Returns:
            (success: bool, message: str)
        """
        pass


class ConnectionManager:
    """
    Manages multiple connections and routes events uniformly.
    
    Responsibilities:
    1. Initialize all configured connections
    2. Receive events from each connection
    3. Put normalized events in shared queue
    4. Route scheduler results back to appropriate connection
    
    Design: All connections feed same scheduler, scheduler is connection-agnostic.
    """
    
    def __init__(self):
        """Initialize connection manager."""
        self.connections: Dict[str, Connection] = {}
        self.logger = None  # Set by scheduler
    
    @abstractmethod
    def initialize_connections(self, config: 'ConfigurationManager') -> Tuple[bool, str]:
        """
        Initialize all connections from configuration.
        
        Parses [connection *] sections and creates appropriate driver instances.
        
        Args:
            config: ConfigurationManager with [connection *] sections
        
        Returns:
            (success: bool, message: str)
        """
        pass
    
    def get_connection(self, connection_name: str) -> Optional[Connection]:
        """Get connection by name."""
        return self.connections.get(connection_name)
    
    def get_all_connections(self) -> Dict[str, Connection]:
        """Get all active connections."""
        return self.connections.copy()
    
    def add_connection(self, connection: Connection) -> None:
        """Register a connection."""
        name = connection.get_connection_name()
        self.connections[name] = connection
    
    def list_connections(self) -> str:
        """Get human-readable list of connections."""
        if not self.connections:
            return "No connections configured"
        
        lines = ["Configured connections:"]
        for name, conn in self.connections.items():
            lines.append(f"  - {name} ({conn.get_source_type()})")
        return "\n".join(lines)
    
    @abstractmethod
    def start_receiving_events(self) -> None:
        """
        Start receiving events from all connections.
        
        Launches listener threads (webhooks, polling, Kafka subscriptions).
        Must be thread-safe - scheduler will consume from shared queue.
        """
        pass
    
    @abstractmethod
    def get_next_event(self, timeout_seconds: float = 1.0) -> Optional[Tuple[Connection, NormalizedEvent]]:
        """
        Get next normalized event from queue.
        
        Blocks until event available or timeout.
        
        Args:
            timeout_seconds: How long to wait for event
        
        Returns:
            (connection, normalized_event) or None if timeout
            
        Connection is returned so scheduler can route results back to it.
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop all connection listeners."""
        pass
