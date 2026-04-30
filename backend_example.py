# Example backend route using FastAPI returning the shape React expects

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

# Add CORS so React dev server can poll
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)

class Job(BaseModel):
    job_id: str
    job_name: str
    status: str
    start_time: Optional[str]
    end_time: Optional[str]
    url: Optional[str]

class Change(BaseModel):
    id: str
    project: str
    branch: str
    subject: str
    patchset: str
    author: str
    url: str
    jobs: List[Job]

class Pipeline(BaseModel):
    name: str
    changes: List[Change]

class StatusResponse(BaseModel):
    last_updated: str
    pipelines: List[Pipeline]

@app.get("/api/status", response_model=StatusResponse)
async def get_state():
    """ 
    This is what Torri's orchestrator generates by reading 
    the state from Redis/Memory every few seconds.
    """
    return {
        "last_updated": "2026-04-23T14:30:00Z",
        "pipelines": [
            {
                "name": "check",
                "changes": [
                    {
                        "id": "1",
                        "project": "frontend-app",
                        "branch": "main",
                        "subject": "Fix login button styling",
                        "patchset": "2",
                        "author": "Catalin",
                        "url": "https://gerrit.torri.dev/frontend-app/1",
                        "jobs": [
                            {"job_id": "j1", "job_name": "lint", "status": "success", "start_time": None, "end_time": None, "url": None},
                            {"job_id": "j2", "job_name": "unit-tests", "status": "running", "start_time": None, "end_time": None, "url": None},
                        ]
                    }
                ]
            },
            {
                "name": "gate",
                "changes": []
            }
        ]
    }
