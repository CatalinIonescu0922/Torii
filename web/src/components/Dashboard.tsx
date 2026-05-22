import { useState } from 'react';
import { useStatusPolling } from '../hooks/useStatusPolling';
import { LogPanel } from './LogPanel';
import type { Pipeline, Change, Job } from '../types/status';

interface SelectedJob {
  job_uuid: string;
  job_name: string;
}

export function Dashboard() {
  const { data, error, isPolling, togglePolling } = useStatusPolling(10000);
  console.log("the data is: ", data)
  const [selectedJob, setSelectedJob] = useState<SelectedJob | null>(null);

  if (error) {
    return <div className="p-4 text-red-500">Error fetching status: {error.message}</div>;
  }

  if (!data) {
    return <div className="p-4 text-gray-500 animate-pulse">Loading CI/CD state...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8 font-sans" style={selectedJob ? { paddingBottom: '42vh' } : {}}>

      {/* Header */}
      <header className="flex justify-between items-center mb-8 border-b pb-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-800">Torri Status</h1>
          <p className="text-sm text-gray-500">
            Last Updated: {new Date(data.last_updated).toLocaleTimeString()}
          </p>
        </div>
        <button
          onClick={togglePolling}
          className={`px-4 py-2 rounded font-medium shadow-sm transition ${
            isPolling ? 'bg-red-50 text-red-600 hover:bg-red-100' : 'bg-green-50 text-green-600 hover:bg-green-100'
          }`}
        >
          {isPolling ? 'Pause Auto-Refresh' : 'Resume Auto-Refresh'}
        </button>
      </header>

      {/* Pipelines Area */}
      <div className="grid gap-8 grid-cols-1 xl:grid-cols-2">
        {data.pipelines.map(pipeline => (
          <PipelineView key={pipeline.name} pipeline={pipeline} onJobClick={setSelectedJob} />
        ))}
      </div>

      {/* Sliding log panel */}
      {selectedJob && (
        <LogPanel
          jobUuid={selectedJob.job_uuid}
          jobName={selectedJob.job_name}
          onClose={() => setSelectedJob(null)}
        />
      )}
    </div>
  );
}

function PipelineView({ pipeline, onJobClick }: { pipeline: Pipeline; onJobClick: (j: SelectedJob) => void }) {
  return (
    <div className="bg-white rounded-xl shadow-md border overflow-hidden">
      <div className="bg-slate-800 px-6 py-4">
        <h2 className="text-lg font-semibold text-white tracking-wide uppercase">
          {pipeline.name} Pipeline
        </h2>
      </div>
      <div className="p-6 space-y-6 bg-slate-50 min-h-[300px]">
        {pipeline.changes.length === 0 ? (
          <div className="text-center text-gray-400 italic py-10">No items currently enqueued</div>
        ) : (
          pipeline.changes.map(change => (
            <ChangeCard key={change.id} change={change} onJobClick={onJobClick} />
          ))
        )}
      </div>
    </div>
  );
}

function ChangeCard({ change, onJobClick }: { change: Change; onJobClick: (j: SelectedJob) => void }) {
  return (
    <div className="bg-white border rounded-lg p-5 shadow-sm hover:shadow transition-shadow">
      <div className="flex justify-between items-start mb-4">
        <div>
          <a href={change.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline font-medium text-lg block">
            {change.project}: {change.subject}
          </a>
          <span className="text-sm text-gray-500 mt-1 inline-block">
            Patchset {change.patchset} • Branch: <span className="font-mono bg-gray-100 px-1 py-0.5 rounded">{change.branch}</span> • Author: {change.author}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3 mt-4 border-t pt-4">
        {change.jobs.map(job => (
          <JobBadge key={job.job_uuid} job={job} onJobClick={onJobClick} />
        ))}
      </div>
    </div>
  );
}

function JobBadge({ job, onJobClick }: { job: Job; onJobClick: (j: SelectedJob) => void }) {
  const statusColors: Record<Job['status'], string> = {
    queued: 'bg-gray-100 text-gray-600 border-gray-200',
    running: 'bg-blue-50 text-blue-700 border-blue-200 animate-pulse',
    success: 'bg-green-50 text-green-700 border-green-200',
    failure: 'bg-red-50 text-red-700 border-red-200',
    timeout: 'bg-orange-50 text-orange-700 border-orange-200',
    cancelled: 'bg-gray-50 text-gray-500 border-gray-200',
  };

  const canShowLogs = job.status !== 'queued';

  return (
    <button
      onClick={() => canShowLogs && onJobClick({ job_uuid: job.job_uuid, job_name: job.job_name })}
      title={canShowLogs ? 'Click to view logs' : undefined}
      className={`border rounded px-3 py-2 text-sm flex flex-col items-center justify-center text-center transition
        ${statusColors[job.status]}
        ${canShowLogs ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}
      `}
    >
      <span className="font-semibold block truncate w-full">{job.job_name}</span>
      <span className="text-xs uppercase tracking-wider mt-1 opacity-80">{job.status}</span>
    </button>
  );
}
