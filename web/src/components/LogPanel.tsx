import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

interface LogPanelProps {
  jobUuid: string;
  jobName: string;
  onClose: () => void;
}

// Resolve the WebSocket URL from the current page origin so it works
// whether you access the UI directly on port 5173 or through nginx.
function wsUrl(jobUuid: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = window.location.host;
  return `${proto}://${host}/ws/job/${jobUuid}/logs`;
}

export function LogPanel({ jobUuid, jobName, onClose }: LogPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      theme: { background: '#1e1e1e', foreground: '#d4d4d4' },
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      fontSize: 13,
      scrollback: 5000,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();
    terminalRef.current = term;

    const ws = new WebSocket(wsUrl(jobUuid));
    wsRef.current = ws;

    ws.onopen = () => term.writeln('\x1b[90m[connected]\x1b[0m');
    ws.onmessage = (event) => {
      const line: string = event.data;
      if (line === '__EOF__') {
        term.writeln('\x1b[90m[job finished]\x1b[0m');
        ws.close();
      } else {
        term.writeln(line);
      }
    };
    ws.onerror = () => term.writeln('\x1b[31m[connection error]\x1b[0m');
    ws.onclose = () => term.writeln('\x1b[90m[disconnected]\x1b[0m');

    const handleResize = () => fit.fit();
    window.addEventListener('resize', handleResize);

    return () => {
      ws.close();
      term.dispose();
      window.removeEventListener('resize', handleResize);
    };
  }, [jobUuid]);

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 flex flex-col"
      style={{ height: '40vh', background: '#1e1e1e' }}
    >
      {/* Drag handle / title bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-t border-gray-600 select-none">
        <span className="text-gray-300 text-sm font-mono">
          Logs — <span className="text-white font-semibold">{jobName}</span>
        </span>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white text-lg leading-none px-1"
          aria-label="Close log panel"
        >
          ✕
        </button>
      </div>

      {/* xterm.js mount point */}
      <div ref={containerRef} className="flex-1 overflow-hidden" />
    </div>
  );
}
