import type { Buildset, Job } from '../types/status';

interface BuildsetDrawerProps {
  buildset: Buildset | null;
  onClose: () => void;
  onJobClick?: (job: Job) => void;
  jobLogs?: string[] | null;
  selectedJobUuid?: string | null;
}

export function BuildsetDrawer({ buildset, onClose, onJobClick, jobLogs, selectedJobUuid }: BuildsetDrawerProps) {
  if (!buildset) return null;

  const formatDurationSeconds = (durationSeconds: number) => {
    if (durationSeconds < 60) return `${durationSeconds.toFixed(3)}s`;
    const minutes = Math.floor(durationSeconds / 60);
    const seconds = durationSeconds % 60;
    return `${minutes}m ${seconds.toFixed(3).padStart(6, '0')}s`;
  };

  const getJobDuration = (job: Job) => {
    if (typeof job.duration_seconds === 'number') {
      return formatDurationSeconds(job.duration_seconds);
    }
    if (!job.start_time) return 'Not started';
    const startTime = new Date(job.start_time).getTime();
    const endTime = job.end_time ? new Date(job.end_time).getTime() : Date.now();
    return formatDurationSeconds(Math.max(0, (endTime - startTime) / 1000));
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'success':
        return 'bg-green-50 text-green-700 border-green-200';
      case 'failure':
        return 'bg-red-50 text-red-700 border-red-200';
      case 'running':
      case 'queued':
        return 'bg-yellow-50 text-yellow-700 border-yellow-200';
      default:
        return 'bg-gray-50 text-gray-700 border-gray-200';
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-white overflow-hidden flex flex-col">
      
      <div className="border-b px-6 py-4 flex justify-between items-center flex-shrink-0">
          <h2 className="text-lg font-bold text-gray-900">Buildset Details</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <span className="text-2xl">&times;</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div>
            <h3 className="text-sm font-medium text-gray-900 mb-3">Build Information</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Project:</span>
                <span className="font-medium text-gray-900">{buildset.project}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Pipeline:</span>
                <span className="font-medium text-gray-900">{buildset.pipeline}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Branch:</span>
                <span className="font-medium text-gray-900">{buildset.branch}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Change:</span>
                <span className="font-medium text-gray-900">{buildset.change_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Patchset:</span>
                <span className="font-medium text-gray-900">{buildset.patchset}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Status:</span>
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  buildset.status === 'succeeded' ? 'bg-green-100 text-green-700' :
                  buildset.status === 'failed' ? 'bg-red-100 text-red-700' :
                  'bg-yellow-100 text-yellow-700'
                }`}>
                  {buildset.status.charAt(0).toUpperCase() + buildset.status.slice(1)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Created:</span>
                <span className="font-medium text-gray-900">{new Date(buildset.created_at).toLocaleString()}</span>
              </div>
            </div>
          </div>

          <div>
            <h3 className="text-sm font-medium text-gray-900 mb-3">Jobs ({buildset.jobs.length})</h3>
            <div className="space-y-2">
              {buildset.jobs.map(job => {
                const isSelected = selectedJobUuid === job.job_uuid;
                return (
                  <div
                    key={job.job_uuid}
                    className={`p-3 rounded border ${getStatusColor(job.status)} ${isSelected ? 'ring-2 ring-blue-300' : ''} cursor-pointer hover:bg-gray-50 transition`}
                    onClick={() => onJobClick?.(job)}
                  >
                    <div className="flex justify-between items-center gap-3">
                      <span className="font-medium truncate">{job.job_name}</span>
                      <span className="text-xs uppercase font-semibold flex-shrink-0">{job.status}</span>
                    </div>
                    <div className="mt-2 flex justify-between items-center gap-3 text-xs">
                      <span>Duration: <span className="font-medium">{getJobDuration(job)}</span></span>
                      <a
                        href={job.log_url || `/buildsets?buildset=${buildset.buildset_uuid}&job=${job.job_uuid}`}
                        onClick={event => event.stopPropagation()}
                        className="font-medium underline underline-offset-2"
                      >
                        Logs
                      </a>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex-1 min-h-0 flex flex-col">
            <h3 className="text-sm font-medium text-gray-900 mb-3">Logs</h3>
            <div className="flex-1 bg-gray-50 rounded-lg p-4 overflow-y-auto font-mono text-xs whitespace-pre-wrap text-gray-800 min-h-0">
              {jobLogs ? (
                jobLogs.map((line, index) => (
                  <span key={index}>{line}{index < jobLogs.length - 1 ? '\n' : ''}</span>
                ))
              ) : (
                <p className="text-xs text-gray-500">Select a job from the list above to view its logs.</p>
              )}
            </div>
           </div>
  </div>
</div>
  );
}
