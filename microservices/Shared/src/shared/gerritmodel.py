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

        # With o=DETAILED_LABELS the per-vote values are inside the "all" list —
        # there is no top-level "value" key in that response format.
        # Take the highest vote from "all". Fall back to the top-level "value" key
        # for any server that returns plain LABELS format instead.
        raw_labels = data.get("labels", {})
        self.labels = {}
        for label_name, label_info in raw_labels.items():
            if not isinstance(label_info, dict):
                continue
            all_votes = label_info.get("all", [])
            if all_votes:
                votes = [
                    int(v["value"])
                    for v in all_votes
                    if isinstance(v, dict) and "value" in v
                ]
                self.labels[label_name] = max(votes) if votes else 0
            else:
                top_value = label_info.get("value")
                self.labels[label_name] = int(top_value) if top_value is not None else 0
        
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
        self.event_source = "gerrit"

    def to_dict(self) -> dict:
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
        return event



class Project:
    name: str
    branches : list[str]
    merge_mode : str

class Pipeline:
    pass


class Job:
    pass
