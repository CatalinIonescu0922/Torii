export interface Job {
    job_id: string;
    job_name: string;
    status: 'queued' | 'running' | 'success' | 'failed' | 'canceled';
    start_time: string | null;
    end_time: string | null;
    url?: string;
  }
  
  export interface Change {
    id: string;
    project: string;
    branch: string;
    subject: string;
    patchset: string;
    author: string;
    url: string;
    jobs: Job[];
  }
  
  export interface Pipeline {
    name: string;
    changes: Change[];
  }
  
  export interface StatusResponse {
    last_updated: string;
    pipelines: Pipeline[];
  }
  