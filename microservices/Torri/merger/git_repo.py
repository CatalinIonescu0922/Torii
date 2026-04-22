import os
import shutil
import subprocess
import threading
from typing import Optional, Dict
from shared.logger_setup import get_logger

class GitCommandError(Exception):
    pass

class GitRepo:
    """
    Core Domain Logic for handling isolated Git operations accurately against
    a local cache. Thread-safe for a single repository directory.
    """
    def __init__(self, workspace_root: str, repo_name: str):
        self.workspace_root = workspace_root
        self.repo_name = repo_name
        self.repo_dir = os.path.join(self.workspace_root, repo_name)
        # Using a threading Lock to prevent race conditions when reading/fetching the same repo
        self._lock = threading.RLock()
        
        # Inject SSH configuration dynamically
        self.env = os.environ.copy()
        self.env['GIT_SSH_COMMAND'] = 'ssh -o StrictHostKeyChecking=no'
        # Can also set GIT_HTTP_LOW_SPEED_LIMIT, GIT_HTTP_LOW_SPEED_TIME for timeout resiliency

    def _run_git_command(self, args: list[str], timeout: int = 120) -> str:
        """Helper to run a git command safely with process timeouts and stderr capture."""
        cmd = ['git'] + args
        logger = get_logger("torri.merger.git", job_id=self.repo_name) # Will use contextual logs if set
        
        try:
            logger.debug("Running command: %s", " ".join(cmd))
            result = subprocess.run(
                cmd,
                cwd=self.repo_dir if os.path.exists(self.repo_dir) else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                timeout=timeout,
                text=True
            )
            if result.returncode != 0:
                raise GitCommandError(f"Git command failed: {result.stderr}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("Git command timed out: %s", " ".join(cmd))
            # Critical: Kill the process implies state could be corrupted
            self._purge_corrupted_repo()
            raise GitCommandError(f"Git operation timed out: {' '.join(cmd)}")
        except Exception as e:
            logger.error("Unexpected error executing %s: %s", " ".join(cmd), e)
            raise

    def _purge_corrupted_repo(self):
        """Purge state entirely so the next fetch will trigger a fresh clone."""
        if os.path.exists(self.repo_dir):
            shutil.rmtree(self.repo_dir, ignore_errors=True)

    def init_or_clone(self, remote_url: str):
        """Ensures the repository exists locally."""
        with self._lock:
            if not os.path.exists(os.path.join(self.repo_dir, ".git")):
                # Ensure parent dir exists
                os.makedirs(os.path.dirname(self.repo_dir), exist_ok=True)
                get_logger("torri.merger.git").info("Cloning fresh repository: %s to %s", remote_url, self.repo_dir)
                try:
                    subprocess.run(
                        ['git', 'clone', remote_url, self.repo_dir],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env=self.env, timeout=300, check=True
                    )
                except subprocess.CalledProcessError as e:
                    self._purge_corrupted_repo()
                    raise GitCommandError(f"Clone failed: {e.stderr.decode('utf-8')}")
            else:
                # Always remove locks defensively if the process died midway before
                lock_file = os.path.join(self.repo_dir, '.git', 'index.lock')
                if os.path.exists(lock_file):
                    os.remove(lock_file)

    def fetch(self, ref: str = "refs/heads/*:refs/remotes/origin/*"):
        """Fetches from the remote Origin."""
        with self._lock:
            self._run_git_command(["fetch", "origin", ref])

    def speculative_merge(self, base_branch: str, patchset_ref: str) -> Optional[str]:
        """
        Attempts to merge a patchset into the base branch locally.
        Returns the merged commit hash if successful.
        Raises GitCommandError if a conflict occurs.
        """
        with self._lock:
            self.fetch(base_branch)
            self.fetch(patchset_ref)
            
            # Switch to base branch
            self._run_git_command(["checkout", "-B", "merge-target", f"origin/{base_branch}"])
            
            # Reset head purely clean
            self._run_git_command(["reset", "--hard", f"origin/{base_branch}"])
            self._run_git_command(["clean", "-xfd"])
            
            # Attempt to merge the fetched patch
            try:
                self._run_git_command(["merge", "--no-edit", "FETCH_HEAD"])
                # Return the new commit hash
                return self._run_git_command(["rev-parse", "HEAD"])
            except GitCommandError as e:
                # Resolve merge state
                self._run_git_command(["merge", "--abort"])
                raise  # Propagate conflict to the server

    def read_files_at_ref(self, ref: str, file_paths: list[str]) -> Dict[str, str]:
        """Reads multiple files off a specific commit or ref, e.g., for config extraction."""
        with self._lock:
            self.fetch(ref)
            results = {}
            for fp in file_paths:
                try:
                    content = self._run_git_command(["show", f"FETCH_HEAD:{fp}"])
                    results[fp] = content
                except GitCommandError:
                    results[fp] = None  # File missing or error reading
            return results
