import os
import shutil
import time
import subprocess
from typing import Dict, List, Optional
import threading
from shared.logger_setup import get_logger
from torri.merger.utils import git_timeout_handler, build_git_env
from torri.merger.ssh_utils import ensure_known_hosts

class GitCommandError(Exception):
    pass

class Repo:
    """
    Phase 2: Repository Abstraction.
    Wraps single Git repositories heavily optimizing for stateless execution.
    """
    def __init__(self, workspace_root: str, repo_name: str, remote_url: str):
        self.workspace_root = workspace_root
        self.repo_name = repo_name
        self.remote_url = remote_url
        self.repo_dir = os.path.join(self.workspace_root, repo_name)
        self._lock = threading.RLock()
        self.env = build_git_env()
        self.logger = get_logger("torri.merger.repo")

    def _run_git(self, args: List[str], timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess:
        """Safely executes git command respecting the Phase 1 Timeout handlers."""
        cmd = ['git'] + args
        cwd = self.repo_dir if os.path.exists(self.repo_dir) else None
        
        self.logger.debug("Executing git %s (cwd=%s, repo_exists=%s)", ' '.join(args), cwd, os.path.exists(self.repo_dir))
        
        with git_timeout_handler(self.repo_dir, timeout=timeout):
            result = subprocess.run(
                cmd, cwd=cwd, env=self.env, timeout=timeout,
                capture_output=True, text=True
            )
            if check and result.returncode != 0:
                # E.g. .git/index.lock exists errors
                if "index.lock" in result.stderr:
                    self.logger.warning("Detected locked index. Force purging corruption.")
                    shutil.rmtree(self.repo_dir, ignore_errors=True)
                error_msg = f"Git command '{' '.join(args)}' failed (exit code {result.returncode})\nStderr: {result.stderr}\nStdout: {result.stdout}"
                self.logger.error(error_msg)
                raise GitCommandError(error_msg)
            return result

    def _apply_aggressive_gc(self):
        """Aggressive Garbage Collection: prevents background Git GC from corrupting synthetic refs."""
        self._run_git(['config', 'gc.autoDetach', 'false'])
        self._run_git(['config', 'gc.pruneExpire', 'now'])
        self._run_git(['config', 'gc.reflogExpire', 'now'])

    def initialize(self, sparse_paths: Optional[List[str]] = None):
        """Dynamic Cloning & Sparse Checkout Initialization."""
        with self._lock:
            if not os.path.exists(os.path.join(self.repo_dir, ".git")):
                self.logger.info("Initializing repository %s at %s from %s", self.repo_name, self.repo_dir, self.remote_url)
                ensure_known_hosts(self.remote_url)
                os.makedirs(self.repo_dir, exist_ok=True)
                self.logger.debug("Created working directory %s", self.repo_dir)
                self._run_git(['init'])
                self.logger.debug("Git init completed")
                self._run_git(['remote', 'add', 'origin', self.remote_url])
                self.logger.debug("Added remote origin: %s", self.remote_url)
                
                self._apply_aggressive_gc()

                if sparse_paths:
                    self.logger.info("Applying sparse checkouts to %s", sparse_paths)
                    self._run_git(['config', 'core.sparseCheckout', 'true'])
                    sparse_file = os.path.join(self.repo_dir, '.git', 'info', 'sparse-checkout')
                    with open(sparse_file, 'w') as f:
                        f.write("\n".join(sparse_paths) + "\n")

                self._git_fetch_with_backoff("refs/heads/*:refs/remotes/origin/*")

    def _git_fetch_with_backoff(self, ref: str, max_retries=3):
        """Exponential backoff for fetches (Network resiliency)."""
        self.logger.info("Fetching ref %s from origin (max_retries=%d)", ref, max_retries)
        retries = 0
        while retries < max_retries:
            try:
                self.logger.debug("Fetch attempt %d/%d for ref %s", retries + 1, max_retries, ref)
                self._run_git(['fetch', 'origin', ref], timeout=300)
                self.logger.info("Successfully fetched %s", ref)
                return
            except GitCommandError as e:
                self.logger.warning("Fetch attempt %d failed: %s", retries + 1, e)
                # Check for fatal index issues that _run_git Purged, which means we must re-init
                if not os.path.exists(self.repo_dir):
                    self.logger.info("Repository directory was purged, reinitializing")
                    self.initialize()
                    return
                retries += 1
                if retries < max_retries:
                    wait_time = 2 ** retries
                    self.logger.debug("Retry in %d seconds...", wait_time)
                    time.sleep(wait_time)
        error_msg = f"Failed to fetch {ref} after {max_retries} attempts."
        self.logger.error(error_msg)
        raise GitCommandError(error_msg)

    def reset_state_hygiene(self, target_branch: str):
        """
        State Hygiene: Bring dirty repo exactly to remote's state WITHOUT modifying local branches.
        Uses detached HEAD to ensure pristine state with zero risk of branch accumulation.
        """
        with self._lock:
            self._git_fetch_with_backoff(target_branch)
            # Clean leaked .git/rebase-merge 
            rebase_dir = os.path.join(self.repo_dir, '.git', 'rebase-merge')
            if os.path.exists(rebase_dir):
                shutil.rmtree(rebase_dir, ignore_errors=True)
            
            # Use detached HEAD to origin exactly (never modify local branches)
            remote_tip = self._run_git(['rev-parse', f'origin/{target_branch}']).stdout.strip()
            self._run_git(['checkout', '-f', '--detach', remote_tip])
            self._run_git(['clean', '-x', '-f', '-d'])
            self.logger.debug("State hygiene: detached HEAD at origin/%s (%s)", target_branch, remote_tip)

    def merge_patchset(self, patchset_ref: str, strategy: str = "merge", base_branch: str = "master", detach_to_base: bool = True) -> str:
        """
        Git Operations against FETCH_HEAD in DETACHED HEAD state.
        Supports both isolated merges (detach_to_base=True) and stacked merges (detach_to_base=False).
        
        - detach_to_base=True: Detach to origin/{base_branch} first (for first merge in stack)
        - detach_to_base=False: Merge on top of current HEAD (for subsequent merges in same job stack)
        
        Returns the synthetic merge commit hash without touching any branches.
        """
        with self._lock:
            self._git_fetch_with_backoff(patchset_ref)
            
            try:
                # For stacking: first merge detaches, subsequent merges work on current HEAD
                if detach_to_base:
                    # CRITICAL: Start from detached HEAD at base_branch tip (not local branch)
                    # This ensures master branch is NEVER modified, only synthetic refs preserve results
                    current_base = self._run_git(['rev-parse', f'origin/{base_branch}']).stdout.strip()
                    self._run_git(['checkout', '-f', '--detach', current_base])
                    self.logger.debug("Detached HEAD at %s (%s) for isolated merge", current_base, base_branch)
                else:
                    # For stacking: work on current HEAD (already positioned by previous merge)
                    current_head = self._run_git(['rev-parse', 'HEAD']).stdout.strip()
                    self.logger.debug("Stacking merge on top of current HEAD: %s", current_head)
                
                if strategy == "cherry-pick":
                    self._run_git(['cherry-pick', 'FETCH_HEAD'])
                elif strategy == "squash":
                    self._run_git(['merge', '--squash', 'FETCH_HEAD'])
                    self._run_git(['commit', '-m', f"Squashed {patchset_ref}"])
                elif strategy == "rebase":
                    self._run_git(['rebase','HEAD', 'FETCH_HEAD'])
                else: 
                    self._run_git(['merge', '--no-edit', '--no-ff', 'FETCH_HEAD'])
                
                # Identify resulting commit hash (result of merge/rebase/cherry-pick on detached HEAD)
                result_hash = self._run_git(['rev-parse', 'HEAD']).stdout.strip()
                self.logger.info("Merge result (strategy=%s, detach_to_base=%s): %s", strategy, detach_to_base, result_hash)
                return result_hash
            except GitCommandError as e:
                self._run_git(['merge', '--abort'], check=False)
                self._run_git(['cherry-pick', '--abort'], check=False)
                self._run_git(['rebase', '--abort'], check=False)
                self.logger.error("Merge operation failed for %s: %s", patchset_ref, str(e))
                raise # Pass conflict up

    def read_files_at_ref(self, ref: str, file_paths: List[str]) -> Dict[str, str]:
        """Reads multiple files off a specific commit or ref, e.g., for config extraction."""
        with self._lock:
            self._git_fetch_with_backoff(ref)
            results = {}
            for fp in file_paths:
                try:
                    content = self._run_git(["show", f"FETCH_HEAD:{fp}"]).stdout
                    results[fp] = content
                except GitCommandError:
                    results[fp] = None  # File missing or error reading
            return results
