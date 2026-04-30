import React from 'react';
import { useStatusPolling } from '../hooks/useStatusPolling';
import type { Pipeline, Change, Job } from '../types/status';

export function Dashboard() {
  // Polling every 5 seconds (5000ms), no websockets used.
  const { data, error, isPolling, togglePolling } = useStatusPolling(5000);

  if (error) {
    return <div className="p-4 text-red-500">Error fetching status: {error.message}</div>;
  }

  if (!data) {
    return <div className="p-4 text-gray-500 animate-pulse">Loading CI/CD state...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8 font-sans">
      
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
          <PipelineView key={pipeline.name} pipeline={pipeline} />
        ))}
      </div>
    </div>
  );
}

function PipelineView({ pipeline }: { pipeline: Pipeline }) {
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
            <ChangeCard key={change.id} change={change} />
          ))
        )}
      </div>
    </div>
  );
}

function ChangeCard({ change }: { change: Change }) {
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
      
      {/* Job Grid for this Change */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3 mt-4 border-t pt-4">
        {change.jobs.map(job => (
          <JobBadge key={job.job_id} job={job} />
        ))}
      </div>
    </div>
  );
}

function JobBadge({ job }: { job: Job }) {
  // Executor-agnostic badge styling (no Jenkins logic)
  const statusColors = {
    queued: 'bg-gray-100 text-gray-600 border-gray-200',
    running: 'bg-blue-50 text-blue-700 border-blue-200 animate-pulse',
    success: 'bg-green-50 text-green-700 border-green-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
    canceled: 'bg-orange-50 text-orange-700 border-orange-200',
  };

  return (
    <a 
      href={job.url || "#"} 
      target="_blank" rel="noreferrer"
      className={`border rounded px-3 py-2 text-sm flex flex-col items-center justify-center text-center transition ${statusColors[job.status]}`}
    >
      <span className="font-semibold block truncate w-full">{job.job_name}</span>
      <span className="text-xs uppercase tracking-wider mt-1 opacity-80">{job.status}</span>
    </a>
  );
}
