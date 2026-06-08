import { useState, useEffect } from 'react';
import type { Buildset, Job } from '../types/status';

interface BuildsetsPageProps {
  onBuildsetClick: (buildset: Buildset) => void;
}

export function BuildsetsPage({ onBuildsetClick }: BuildsetsPageProps) {
  const [buildsets, setBuildsets] = useState<Buildset[]>([]);
  const [filteredBuildsets, setFilteredBuildsets] = useState<Buildset[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [pipelineFilter, setPipelineFilter] = useState<string | null>(null);
  const [projectFilter, setProjectFilter] = useState<string | null>(null);

  useEffect(() => {
    const fetchBuildsets = async () => {
      try {
        setLoading(true);
        const res = await fetch('/api/buildsets?limit=200');
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const data: Buildset[] = await res.json();
        setBuildsets(data);
      } catch (err) {
        console.error('Failed to fetch buildsets:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchBuildsets();
    const interval = setInterval(fetchBuildsets, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let filtered = buildsets;

    if (searchText) {
      const query = searchText.toLowerCase();
      filtered = filtered.filter(bs =>
        bs.change_id.toLowerCase().includes(query) ||
        bs.project.toLowerCase().includes(query) ||
        bs.branch.toLowerCase().includes(query)
      );
    }

    if (statusFilter) {
      filtered = filtered.filter(bs => bs.status === statusFilter);
    }

    if (pipelineFilter) {
      filtered = filtered.filter(bs => bs.pipeline === pipelineFilter);
    }

    if (projectFilter) {
      filtered = filtered.filter(bs => bs.project === projectFilter);
    }

    setFilteredBuildsets(filtered);
  }, [buildsets, searchText, statusFilter, pipelineFilter, projectFilter]);

  const getStatusDisplay = (status: string) => {
    switch (status) {
      case 'succeeded':
        return { bg: 'bg-green-50', text: 'text-green-700', label: 'Success' };
      case 'failed':
        return { bg: 'bg-red-50', text: 'text-red-700', label: 'Failed' };
      case 'running':
        return { bg: 'bg-yellow-50', text: 'text-yellow-700', label: 'Running' };
      default:
        return { bg: 'bg-gray-50', text: 'text-gray-700', label: status };
    }
  };

  const formatTime = (isoString: string) => {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  };

  const getJobSummary = (jobs: Job[]) => {
    const succeeded = jobs.filter(j => j.status === 'success').length;
    const failed = jobs.filter(j => j.status === 'failure').length;
    const running = jobs.filter(j => j.status === 'running' || j.status === 'queued').length;

    return { succeeded, failed, running };
  };

  const uniquePipelines = Array.from(new Set(buildsets.map(bs => bs.pipeline)));
  const uniqueProjects = Array.from(new Set(buildsets.map(bs => bs.project)));

  if (loading && buildsets.length === 0) {
    return <div className="text-center text-gray-500 py-8">Loading buildsets...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow-sm p-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Search</label>
          <input
            type="text"
            placeholder="Change number, project, or branch..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
            <select
              value={statusFilter || ''}
              onChange={e => setStatusFilter(e.target.value || null)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All</option>
              <option value="succeeded">Success</option>
              <option value="failed">Failed</option>
              <option value="running">Running</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Pipeline</label>
            <select
              value={pipelineFilter || ''}
              onChange={e => setPipelineFilter(e.target.value || null)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All</option>
              {uniquePipelines.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Project</label>
            <select
              value={projectFilter || ''}
              onChange={e => setProjectFilter(e.target.value || null)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All</option>
              {uniqueProjects.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow-sm overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Change</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pipeline</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Jobs</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {filteredBuildsets.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-gray-400">
                  No buildsets found
                </td>
              </tr>
            ) : (
              filteredBuildsets.map(bs => {
                const statusDisplay = getStatusDisplay(bs.status);
                const jobs = getJobSummary(bs.jobs);
                return (
                  <tr key={bs.buildset_uuid} className="hover:bg-gray-50 cursor-pointer transition">
                    <td className="px-6 py-4">
                      <span className={`inline-block px-2 py-1 rounded text-xs font-medium ${statusDisplay.bg} ${statusDisplay.text}`}>
                        {statusDisplay.label}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm">
                        <div className="font-medium text-gray-900">{bs.project}</div>
                        <div className="text-gray-500">Change {bs.change_id} • Patchset {bs.patchset}</div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">{bs.pipeline}</td>
                    <td className="px-6 py-4 text-sm space-x-1">
                      {jobs.succeeded > 0 && <span className="inline-block px-2 py-1 bg-green-100 text-green-700 rounded text-xs">Success {jobs.succeeded}</span>}
                      {jobs.failed > 0 && <span className="inline-block px-2 py-1 bg-red-100 text-red-700 rounded text-xs">Failed {jobs.failed}</span>}
                      {jobs.running > 0 && <span className="inline-block px-2 py-1 bg-yellow-100 text-yellow-700 rounded text-xs">Running {jobs.running}</span>}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">{formatTime(bs.created_at)}</td>
                    <td className="px-6 py-4">
                      <button
                        onClick={() => onBuildsetClick(bs)}
                        className="px-3 py-1 bg-blue-50 text-blue-600 rounded hover:bg-blue-100 text-sm font-medium"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
