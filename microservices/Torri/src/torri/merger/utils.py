import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from typing import Dict, Any, List

from shared.logger_setup import get_logger

logger = get_logger("torri.merger.utils")

# --- Phase 1: Foundational Utilities ---

@contextmanager
def git_timeout_handler(repo_dir: str, timeout: int = 120):
    """
    Context manager that watches for specific exit codes or timeouts.
    If a process hangs and is killed (or times out), it aggressively purges 
    the corrupted repo to force a fresh clone.
    """
    try:
        yield
    except subprocess.TimeoutExpired as e:
        logger.error(f"Git operation timed out in {repo_dir}: {e}")
        if os.path.exists(repo_dir):
            logger.warning(f"Purging corrupted repository state at {repo_dir}")
            shutil.rmtree(repo_dir, ignore_errors=True)
        raise
    except subprocess.CalledProcessError as e:
        # If killed (-9 SIGKILL)
        if e.returncode == -9 or e.returncode == 137:
            logger.error(f"Git operation was SIGKILL'ed in {repo_dir}: {e}")
            if os.path.exists(repo_dir):
                shutil.rmtree(repo_dir, ignore_errors=True)
        raise

def build_git_env() -> Dict[str, str]:
    """
    Environment Sandbox: Injects low-speed limits to fail fast on hanging 
    network I/O, and isolates SSH keys.
    """
    env = os.environ.copy()
    # Fail fast if transfer drops below 1KB/s for 30 seconds
    env['GIT_HTTP_LOW_SPEED_LIMIT'] = '1000'
    env['GIT_HTTP_LOW_SPEED_TIME'] = '30'
    env['GIT_SSH_COMMAND'] = 'ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30'
    # Disable terminal prompts
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['GIT_ASKPASS'] = '/bin/false'
    return env

class LineMapper:
    """
    Diff Mapping: Parses unified diffs to map source line numbers to patch line numbers.
    """
    # Matches unified diff hunk headers: @@ -source_start,source_len +patch_start,patch_len @@
    HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')
    
    @classmethod
    def parse_diff(cls, diff_text: str) -> List[int]:
        """Returns starting line numbers of patch hunks."""
        lines = []
        for line in diff_text.splitlines():
            match = cls.HUNK_RE.match(line)
            if match:
                lines.append(int(match.group(1)))
        return lines

