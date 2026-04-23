import { useState, useEffect, useCallback } from 'react';
import { StatusResponse } from '../types/status';

export function useStatusPolling(pollIntervalMs: number = 5000) {
  const [data, setData] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isPolling, setIsPolling] = useState<boolean>(true);

  const fetchStatus = useCallback(async () => {
    if (!isPolling) return;
    try {
      // In production, this points to your FastAPI/Python backend
      const res = await fetch('/api/status');
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'));
      // Optional: you can auto-pause polling here if there's a hard crash
    }
  }, [isPolling]);

  useEffect(() => {
    // Initial fetch
    fetchStatus();

    // Setup polling interval
    const intervalId = setInterval(fetchStatus, pollIntervalMs);

    return () => clearInterval(intervalId); // Cleanup on unmount
  }, [fetchStatus, pollIntervalMs]);

  return { 
    data, 
    error, 
    isPolling, 
    togglePolling: () => setIsPolling(p => !p) 
  };
}
