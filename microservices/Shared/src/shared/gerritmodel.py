known_events = [
    'patchset-created', 'comment-added', 'change-merged',
    'change-abandoned', 'change-restored', 'ref-updated',
    'wip-state-changed', 'private-state-changed', 'reviewer-added'
]

known_labels = [
    'Verified' , 'Code-Review' , 'GateKeeeper'
]


class GerritChange:
    """Gerrit change information"""
    def __init__(self):
        self.base_url = ""
        self.project = ""
        self.branch = ""
        self.id = ""
        self.number = 0
        self.patchset = 0
        self.current_revision = {}
        self.subject = ""
        self.url = ""
        self.submit_type = ""
        self.status = ""
        self.wip = False
        self.private = False
        self.needs_changes = []
        self.needed_by_changes = []
        self.author = ""
        # label_name -> current vote value (int), e.g. {"Code-Review": 2, "Verified": 1}
        self.labels = {}

    def update(self, data):
        revisions = data.get("revisions", {})
        current_revision_id = data.get("current_revision")
        if current_revision_id is not None:
            self.current_revision = revisions.get(current_revision_id, {})
            patchset_number = self.current_revision.get("_number")
            if patchset_number is not None:
                self.patchset = int(patchset_number)

        self.project = str(data.get("project", ""))
        self.branch = str(data.get("branch", ""))
        self.id = str(data.get("id", ""))
        self.number = int(data.get("_number", 0))
        self.subject = str(data.get("subject", ""))
        self.status = str(data.get("status", ""))
        self.submit_type = str(data.get("submit_type", ""))
        self.wip = bool(data.get("work_in_progress", False))
        self.private = bool(data.get("private", False))
        owner = data.get("owner", {})
        self.author = str(owner.get("name", ""))
        self.url = ('%s/c/%s/+/%s' % (self.base_url , self.project , self.number))

        # Each label entry has a "value" field with the current aggregate vote.
        # If nobody voted yet the field is absent; default to 0.
        raw_labels = data.get("labels", {})
        self.labels = {
            label_name: int(label_info.get("value", 0))
            for label_name, label_info in raw_labels.items()
            if isinstance(label_info, dict)
        }
        
    def __repr__(self):
        return '<Change 0x%x %s %s>' % (id(self) , self.project ,self.number)


class GerritTriggerEvent:
    """An event that can trigger a zuul pipeline run"""
    def __init__(self):
        self.data = {}
        self.type = ""
        self.project_name = ""
        self.trigger_name = ""
        self.event_handle_time = None
        self.account = {}
        self.change_number = ""
        self.change_url = ""
        self.patch_number = ""
        self.refspec = ""
        self.approvals = []
        self.branch = ""
        self.comment = ""
        self.ref = ""
        self.oldrev = ""
        self.newrev = ""
        self.timespec = ""
        self.pipeline_name = ""
        self.query_future = None
        self.source = None
        self.change_details = None

    def to_dict(self) -> dict:
        change = None
        if self.change_details is not None:
            c = self.change_details
            change = {
                "base_url": c.base_url,
                "project": c.project,
                "branch": c.branch,
                "id": c.id,
                "number": c.number,
                "patchset": c.patchset,
                "subject": c.subject,
                "url": c.url,
                "status": c.status,
                "wip": c.wip,
                "private": c.private,
                "author": c.author,
                "labels": c.labels,
            }
        return {
            "type": self.type,
            "project_name": self.project_name,
            "change_number": self.change_number,
            "patch_number": self.patch_number,
            "branch": self.branch,
            "comment": self.comment,
            "ref": self.ref,
            "oldrev": self.oldrev,
            "newrev": self.newrev,
            "change_details": change,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GerritTriggerEvent":
        event = cls()
        event.type = data.get("type", "")
        event.project_name = data.get("project_name", "")
        event.change_number = data.get("change_number", "")
        event.patch_number = data.get("patch_number", "")
        event.branch = data.get("branch", "")
        event.comment = data.get("comment", "")
        event.ref = data.get("ref", "")
        event.oldrev = data.get("oldrev", "")
        event.newrev = data.get("newrev", "")
        raw_change = data.get("change_details")
        if raw_change:
            c = GerritChange()
            c.base_url = raw_change.get("base_url", "")
            c.project = raw_change.get("project", "")
            c.branch = raw_change.get("branch", "")
            c.id = raw_change.get("id", "")
            c.number = raw_change.get("number", 0)
            c.patchset = raw_change.get("patchset", 0)
            c.subject = raw_change.get("subject", "")
            c.url = raw_change.get("url", "")
            c.status = raw_change.get("status", "")
            c.wip = raw_change.get("wip", False)
            c.private = raw_change.get("private", False)
            c.author = raw_change.get("author", "")
            c.labels = raw_change.get("labels", {})
            event.change_details = c
        return event



class Project:
    name: str
    branches : list[str]
    merge_mode : str

class Pipeline:
    pass


class Job:
    pass
