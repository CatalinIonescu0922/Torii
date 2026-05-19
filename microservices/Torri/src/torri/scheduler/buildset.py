"""
Buildset: one run of all jobs for a single change+patchset in a pipeline.

A buildset groups every job that needs to pass before the change can merge.
The scheduler creates a buildset when it dispatches work to the executor.
The result consumer updates it as jobs finish and fires on_done when all are done.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List


@dataclass
class JobInBuildset:
    job_uuid: str
    job_name: str
    status: str = "queued"  # queued, running, success, failure, timeout, cancelled


@dataclass
class Buildset:
    buildset_uuid: str
    change_id: str
    patchset: str
    pipeline: str
    project: str
    branch: str
    jobs: List[JobInBuildset]
    status: str = "running"  # running, succeeded, failed
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "buildset_uuid": self.buildset_uuid,
            "change_id": self.change_id,
            "patchset": self.patchset,
            "pipeline": self.pipeline,
            "project": self.project,
            "branch": self.branch,
            "status": self.status,
            "created_at": self.created_at,
            "jobs": [
                {"job_uuid": j.job_uuid, "job_name": j.job_name, "status": j.status}
                for j in self.jobs
            ],
        }
