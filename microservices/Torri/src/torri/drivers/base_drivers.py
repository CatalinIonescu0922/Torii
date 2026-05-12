"""
Base driver classes - abstract interfaces for driver pattern implementation.

Design principle: Open/Closed - Open for extension (new drivers), Closed for modification (core code).
Each driver type can be extended independently without modifying core scheduler logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional


class ChangeSource(ABC):
    """
    Abstract interface for receiving and parsing changes from VCS.
    
    Implementations: GerritChangeSource, GitHubChangeSource, GitLabChangeSource, etc.
    """
    
    @abstractmethod
    def parse_event(self, event_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Parse raw VCS event into standardized change format.
        
        Args:
            event_data: Raw event from VCS (Kafka message JSON, webhook payload, etc.)
        
        Returns:
            (success: bool, parsed_data: Dict)
            
        Parsed data should contain:
        {
            'change_id': str,
            'change_number': int,
            'patchset': int,
            'event_type': str (e.g., 'patchset-created'),
            'project': str,
            'branch': str,
            'author': str,
            'commit_hash': str,
            'raw_event': event_data  # Store original for debugging
        }
        """
        pass
    
    @abstractmethod
    def get_change_details(self, change_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Retrieve full change details from VCS API.
        
        Args:
            change_id: Unique change identifier (change number for Gerrit, PR ID for GitHub, etc.)
        
        Returns:
            (success: bool, details: Dict)
        """
        pass


class ValidationGate(ABC):
    """
    Abstract interface for validating pipeline entry criteria.
    
    Pipeline validation rules vary by VCS:
    - Gerrit: check Approved, Code-Review labels
    - GitHub: check PR approvals, status checks
    - GitLab: check approvals, merge requests
    
    Implementations: GerritValidationGate, GitHubValidationGate, etc.
    """
    
    @abstractmethod
    def can_enter_pipeline(
        self,
        change_id: str,
        patchset: str,
        pipeline_name: str
    ) -> Tuple[bool, str]:
        """
        Check if change meets pipeline entry criteria.
        
        Args:
            change_id: Unique change identifier
            patchset: Patchset/revision identifier
            pipeline_name: Pipeline to enter ('check', 'gate', 'post')
        
        Returns:
            (can_enter: bool, message: str)
            
        If cannot enter, should post rejection reason to VCS as comment/review.
        """
        pass
    
    @abstractmethod
    def post_message(
        self,
        change_id: str,
        message: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, str]:
        """
        Post message/comment to VCS change.
        
        Args:
            change_id: Unique change identifier
            message: Comment text
            labels: Optional VCS-specific labels (e.g., Gerrit Code-Review+1)
        
        Returns:
            (success: bool, response: str)
        """
        pass


class MergeDriver(ABC):
    """
    Abstract interface for submitting/merging changes in VCS.
    
    Different VCS systems have different merge strategies:
    - Gerrit: rebase and merge via REST API
    - GitHub: merge via GitHub API (squash, rebase, merge options)
    - GitLab: merge request acceptance
    
    Implementations: GerritMergeDriver, GitHubMergeDriver, etc.
    """
    
    @abstractmethod
    def submit_change(self, change_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Submit/merge change in VCS.
        
        Args:
            change_id: Unique change identifier
        
        Returns:
            (success: bool, response: Dict)
            
        Response should contain VCS-specific details:
        {
            'status': 'MERGED'|'FAILED',
            'commit_hash': str,
            'message': str,
            'submission_time': str,
        }
        """
        pass
    
    @abstractmethod
    def can_submit(self, change_id: str) -> Tuple[bool, str]:
        """
        Check if change is ready for submission (has required approvals, etc.)
        
        Args:
            change_id: Unique change identifier
        
        Returns:
            (can_submit: bool, reason: str)
        """
        pass
    
    @abstractmethod
    def get_merge_status(self, change_id: str) -> str:
        """
        Get current merge status of change.
        
        Returns: 'OPEN', 'MERGED', 'ABANDONED', 'FAILED', etc. (VCS-specific)
        """
        pass


class SyntheticRefProvider(ABC):
    """
    Abstract interface for providing synthetic refs for testing.
    
    Synthetic refs allow running CI/CD on merged code before actual merge.
    
    Implementations: GerritSyntheticRefProvider, GitHubSyntheticRefProvider, etc.
    """
    
    @abstractmethod
    def create_synthetic_ref(self, change_id: str) -> Tuple[bool, str]:
        """
        Create synthetic ref for change.
        
        Args:
            change_id: Unique change identifier
        
        Returns:
            (success: bool, synthetic_ref: str)
            
        Example: "refs/changes/23/1123/1" for Gerrit
        """
        pass
    
    @abstractmethod
    def get_synthetic_ref(self, change_id: str) -> Optional[str]:
        """
        Get existing synthetic ref for change.
        
        Returns: Ref string or None if not available
        """
        pass
