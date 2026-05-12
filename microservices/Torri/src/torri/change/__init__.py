"""
Abstract Change class and implementations.

Base class for all VCS change types (Gerrit, GitHub, GitLab, Bitbucket, etc.)
Each change type implements canMerge() and merge() based on its VCS rules.

Design: Polymorphism - scheduler works with Change abstraction, not concrete types.

Usage:
  change = GerritChange(...)  # or GitHubChange(...), GitLabChange(...)
  
  if change.canMerge():
    success, msg = change.merge()
  else:
    print("Cannot merge")
"""

import abc
from typing import Tuple, Optional, Dict, Any
from enum import Enum


class MergeStatus(str, Enum):
    """Change merge status."""
    OPEN = "OPEN"
    MERGED = "MERGED"
    ABANDONED = "ABANDONED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class Change(metaclass=abc.ABCMeta):
    """
    Abstract base class for all VCS change types.
    
    A change represents a code review (Gerrit), pull request (GitHub), 
    merge request (GitLab), etc. Each type implements VCS-specific logic
    for checking merge readiness and performing merge.
    
    Subclasses: GerritChange, GitHubChange, GitLabChange, etc.
    """
    
    def __init__(self, source: str, connection_name: str):
        """
        Initialize change.
        
        Args:
            source: VCS type ('gerrit', 'github', 'gitlab', etc.)
            connection_name: Name of connection managing this change
        """
        self.source = source
        self.connection_name = connection_name
        
        # Basic change information (all types have these)
        self.change_id = None  # Unique identifier
        self.project = None
        self.branch = None
        self.status = None  # OPEN, MERGED, ABANDONED, etc.
        self.author = None
    
    @abc.abstractmethod
    def canMerge(self) -> Tuple[bool, str]:
        """
        Check if change is ready for merge.
        
        VCS-specific checks:
        - Gerrit: Code-Review +2, Verified +1, no conflicts
        - GitHub: PRs approved, status checks pass, no conflicts
        - GitLab: MR approved, pipeline passed, no conflicts
        
        Returns:
            (can_merge: bool, reason: str)
            
        Examples:
            (True, "Ready to merge")
            (False, "Waiting for Code-Review +2")
            (False, "Change has merge conflicts")
        """
        pass
    
    @abc.abstractmethod
    def merge(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Merge the change in the VCS.
        
        VCS-specific merge operations:
        - Gerrit: SSH gerrit review --submit or REST /a/changes/{id}/submit
        - GitHub: API PUT /repos/.../pulls/{id}/merge
        - GitLab: API PUT /projects/.../merge_requests/{id}/merge
        
        Returns:
            (success: bool, response: Dict)
            
        Response contains:
            {
                'status': 'MERGED' | 'FAILED',
                'merged_by': str,
                'merged_at': str,
                'commit_sha': str,
                'message': str,
                'errors': str (if failed)
            }
        """
        pass
    
    @abc.abstractmethod
    def getMergeStatus(self) -> MergeStatus:
        """
        Get current merge status from VCS.
        
        Returns:
            MergeStatus enum value
        """
        pass
    
    @abc.abstractmethod
    def postMessage(self, message: str, labels: Optional[Dict] = None) -> bool:
        """
        Post message/comment to change in VCS.
        
        Returns:
            bool: Success status
        """
        pass


# Import implementations (avoid circular imports by importing here)
try:
    from torri.change.gerrit import GerritChange
except ImportError:
    GerritChange = None

try:
    from torri.change.factory import ChangeFactory
except ImportError:
    ChangeFactory = None

# Exports
__all__ = [
    'Change',
    'MergeStatus',
    'GerritChange',
    'ChangeFactory',
]
        
        Args:
            message: Comment text
            labels: VCS-specific labels/votes (optional)
        
        Returns:
            bool: Success status
        """
        pass
    
    def __repr__(self):
        """String representation."""
        return f'<Change {self.source}:{self.project}/{self.change_id}>'
