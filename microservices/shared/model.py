"""
Shared Pydantic models for Gerrit events.
Layer B: Validation Layer
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


# ============================================================================
# GERRIT EVENT MODELS (Input from Kafka)
# ============================================================================

class Account(BaseModel):
    """Gerrit user account information"""
    name: Optional[str] = None
    email: str
    username: Optional[str] = None

class Change(BaseModel):
    """Gerrit change information"""
    project: str
    branch: str
    id: str
    number: int
    subject: str
    owner: Account
    url: Optional[str] = None
    commitMessage: Optional[str] = None
    createdOn: Optional[int] = None
    status: Optional[str] = None
    wip: Optional[bool] = False
    private: Optional[bool] = False


class Approval(BaseModel):
    """Label approval/vote information"""
    type: str  # e.g., "Verified", "Code-Review"
    description: Optional[str] = None
    value: str  # e.g., "1", "-1", "2"
    oldValue: Optional[str] = None


class PatchSetCreatedEvent(BaseModel):
    """Event emitted when a new patchset is uploaded"""
    type: Literal["patchset-created"]
    change: Change
    uploader: Account
    eventCreatedOn: Optional[int] = None


class CommentAddedEvent(BaseModel):
    """Event emitted when comments/labels are added to a change"""
    type: Literal["comment-added"]
    change: Change
    author: Account
    approvals: Optional[List[Approval]] = Field(default_factory=list)
    comment: Optional[str] = None
    eventCreatedOn: Optional[int] = None


class ChangeMergedEvent(BaseModel):
    """Event emitted when a change is merged"""
    type: Literal["change-merged"]
    change: Change
    submitter: Account
    newRev: Optional[str] = None
    eventCreatedOn: Optional[int] = None


class DraftPublishedEvent(BaseModel):
    """Event emitted when a draft is published"""
    type: Literal["draft-published"]
    change: Change
    uploader: Account
    eventCreatedOn: Optional[int] = None

class RoutingDecision(BaseModel):
    """Handler decision output"""
    action: Literal["PROCESS", "IGNORE", "ERROR"]
    reason: str = ""



class Project(BaseModel):
    name: str
    branches : list[str]
    merge_mode : str

class Pipeline(BaseModel):
    pass


class Job(BaseModel):
    pass
