import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { Dashboard } from './components/Dashboard';
import { BuildsetsPage } from './components/Buildsets';
import { BuildsetDrawer } from './components/BuildsetDrawer';
import { Layout } from './components/Layout';
import type { Buildset, Job } from './types/status';

function App() {
  const [selectedBuildset, setSelectedBuildset] = useState<Buildset | null>(null);
  const [jobLogs, setJobLogs] = useState<string[] | null>(null);

  useEffect(() => {
    setJobLogs(null);
  }, [selectedBuildset]);

  const handleJobClick = async (job: Job) => {
    console.log('Job clicked:', job);
    try {
      const response = await fetch(`/api/job/${job.job_uuid}/logs`);
      if (response.ok) {
        const data = await response.json();
        setJobLogs(data.lines);
      } else {
        setJobLogs(["Failed to fetch logs"]);
      }
    } catch (error) {
      setJobLogs(["Error fetching logs"]);
    }
  };

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/buildsets"
            element={
              <>
                <BuildsetsPage onBuildsetClick={setSelectedBuildset} />
                <BuildsetDrawer
                  buildset={selectedBuildset}
                  onClose={() => setSelectedBuildset(null)}
                  onJobClick={handleJobClick}
                  jobLogs={jobLogs}
                />
              </>
            }
          />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
