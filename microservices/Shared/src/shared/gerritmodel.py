from dataclasses import dataclass
from typing import Optional, List, Literal
from datetime import datetime


known_events = [
    'patchset-created', 'comment-added', 'change-merged', 
    'change-abandoned', 'change-restored', 'ref-updated', 
    'reviewer-added', 'wip-state-changed', 'private-state-changed'
]

known_labels = [
    'Verified' , 'Code-Review' , 'GateKeeeper'
]


class GerritChange():
    """Gerrit change information"""
    def __init__(self) -> None:
        self.project: str = ""
        self.branch: str = ""
        self.id: str = ""
        self.number: int = 0
        self.subject: str = ""
        self.url: str = "" 
        self.commitMessage: str = ""
        self.createdOn: int = 0
        self.status: str = ""
        self.wip: bool = False
        self.private: bool = False
        self.needs_changes: list = []
        self.needed_by_changes: list = []
        self.author: str = ""

@dataclass(slots=True)
class GerritTriggerEvent:
    """An event that can trigger a zuul pipeline run"""
    def __init__(self):
        self.data = None
        # common
        self.type = None
        self.project_name = None
        self.trigger_name = None
        self.event_handle_time = None
        # Representation of the user account that performed the event.
        self.account = None
        # patchset-created, comment-added, etc.
        self.change_number = None
        self.change_url = None
        self.patch_number = None
        self.refspec = None
        self.approvals = []
        self.branch = None
        self.comment = None
        # ref-updated
        self.ref = None
        self.oldrev = None
        self.newrev = None
        # timer
        self.timespec = None
        # zuultrigger
        self.pipeline_name = None
        # For events that arrive with a destination pipeline (eg, from
        # an admin command, etc):
        self.query_future = None
        self.source = None



class Project():
    name: str
    branches : list[str]
    merge_mode : str

class Pipeline():
    pass


class Job():
    pass
