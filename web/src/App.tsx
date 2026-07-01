import { BrowserRouter, Routes, Route, useSearchParams } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';
import { Dashboard } from './components/Dashboard';
import { BuildsetsPage } from './components/Buildsets';
import { BuildsetDrawer } from './components/BuildsetDrawer';
import { Layout } from './components/Layout';
import type { Buildset, Job } from './types/status';

function BuildsetsRoute() {
  const [selectedBuildset, setSelectedBuildset] = useState<Buildset | null>(null);
  const [jobLogs, setJobLogs] = useState<string[] | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedBuildsetUuid = searchParams.get('buildset');
  const selectedJobUuid = searchParams.get('job');

  useEffect(() => {
    setJobLogs(null);
  }, [selectedBuildset]);

  const fetchJobLogs = useCallback(async (job: Job) => {
    try {
      const response = await fetch(`/api/job/${job.job_uuid}/logs`);
      if (response.ok) {
        const data = await response.json();
        setJobLogs(data.lines);
      } else {
        setJobLogs(["Failed to fetch logs"]);
      }
    } catch {
      setJobLogs(["Error fetching logs"]);
    }
  }, []);

  useEffect(() => {
    if (!selectedBuildsetUuid) {
      setSelectedBuildset(null);
      setJobLogs(null);
      return;
    }
    if (selectedBuildset?.buildset_uuid === selectedBuildsetUuid) return;

    let cancelled = false;
    const fetchBuildset = async () => {
      try {
        const response = await fetch(`/api/buildset/${selectedBuildsetUuid}`);
        if (!response.ok) return;
        const data: Buildset = await response.json();
        if (!cancelled) setSelectedBuildset(data);
      } catch {
        if (!cancelled) setSelectedBuildset(null);
      }
    };

    fetchBuildset();
    return () => {
      cancelled = true;
    };
  }, [selectedBuildset?.buildset_uuid, selectedBuildsetUuid]);

  useEffect(() => {
    if (!selectedBuildset || !selectedJobUuid) return;
    const selectedJob = selectedBuildset.jobs.find(job => job.job_uuid === selectedJobUuid);
    if (selectedJob) fetchJobLogs(selectedJob);
  }, [fetchJobLogs, selectedBuildset, selectedJobUuid]);

  const handleBuildsetClick = (buildset: Buildset) => {
    setSelectedBuildset(buildset);
    setSearchParams({ buildset: buildset.buildset_uuid });
  };

  const handleJobClick = (job: Job) => {
    if (selectedBuildset) {
      setSearchParams({ buildset: selectedBuildset.buildset_uuid, job: job.job_uuid });
    }
    fetchJobLogs(job);
  };

  const handleClose = () => {
    setSelectedBuildset(null);
    setJobLogs(null);
    setSearchParams({});
  };

  return (
    <>
      <BuildsetsPage onBuildsetClick={handleBuildsetClick} />
      <BuildsetDrawer
        buildset={selectedBuildset}
        onClose={handleClose}
        onJobClick={handleJobClick}
        jobLogs={jobLogs}
        selectedJobUuid={selectedJobUuid}
      />
    </>
  );
}

function App() {
  return (
    <BrowserRouter basename="/t">
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/buildsets"
            element={<BuildsetsRoute />}
          />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
