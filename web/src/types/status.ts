export interface Job {
  job_uuid: string;
  job_name: string;
  status: 'queued' | 'running' | 'success' | 'failure' | 'timeout' | 'cancelled';
}

export interface Change {
  id: string;
  project: string;
  branch: string;
  subject: string;
  patchset: string;
  author: string;
  url: string;
  buildset_uuid: string;
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

export interface Buildset {
  buildset_uuid: string;
  change_id: string;
  patchset: string;
  pipeline: string;
  project: string;
  branch: string;
  status: 'running' | 'succeeded' | 'failed';
  created_at: string;
  jobs: Job[];
}
