from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class MergeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"

class MergeAction(str, Enum):
    SPECULATIVE_MERGE = "SPECULATIVE_MERGE"
    READ_CONFIG = "READ_CONFIG"

class MergeRequest(BaseModel):
    job_id: str
    trace_id: Optional[str] = None
    target_repository: str
    base_branch: str
    patchset_refs: list[str]
    action: MergeAction
    # E.g., for READ_CONFIG
    files_to_read: Optional[list[str]] = Field(default_factory=list)

class MergeResponse(BaseModel):
    job_id: str
    status: MergeStatus
    merged_commit_hash: Optional[str] = None
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)
    error_message: Optional[str] = None
