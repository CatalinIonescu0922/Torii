import re
import uuid
import os
from typing import Dict, List, Optional
import networkx as nx  # Using networkx or dicts for simpler Tree representation
from shared.logger_setup import get_logger
from torri.merger.repo import Repo, GitCommandError

class MergerTreeError(Exception):
    """Raised when repository checkouts overlap on disk."""
    pass

class SpeculativeMergeItem:
    def __init__(self, target_repo_url: str, repo_name: str, base_branch: str, patchset_ref: str, strategy: str = "merge"):
        self.target_repo_url = target_repo_url
        self.repo_name = repo_name
        self.base_branch = base_branch
        self.patchset_ref = patchset_ref
        # Supports: 'merge', 'cherry-pick', 'squash', 'rebase'
        self.strategy = strategy

class Merger:
    """
    Phase 3: The Multi-Repo Workspace Orchestrator.
    Manages building speculative namespaces, tagging synthetic states, 
    and checkpointing for complex dependencies natively.
    """
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.logger = get_logger("torri.merger.orchestrator")
        self.repos: Dict[str, Repo] = {}
        # Stores mapped checkouts to validate overlap
        self.checkout_paths = set()

    def _validate_merger_tree(self, new_dir: str):
        """
        Collision Detection (MergerTree mapping abstract structures):
        Prevent nested clones (e.g. /app and /app/api)
        """
        for existing in self.checkout_paths:
            if existing.startswith(new_dir + os.sep) or new_dir.startswith(existing + os.sep):
                raise MergerTreeError(f"Collision detected: {new_dir} conflicts with {existing}")
        self.checkout_paths.add(new_dir)

    def _get_repo(self, target_url: str, repo_name: str) -> Repo:
        """Workspace Layout mapping abstract names to physical."""
        physical_path = os.path.join(self.workspace_root, repo_name)
        if repo_name not in self.repos:
            self._validate_merger_tree(physical_path)
            # By default sparse checkout config can be initialized here
            repo = Repo(self.workspace_root, repo_name, target_url)
            repo.initialize() 
            self.repos[repo_name] = repo
        return self.repos[repo_name]

    def _saveRepoState(self, repo: Repo) -> Dict[str, str]:
        """
        Repo State Checkpointing: Records all packed-refs mappings 
        before modifying the base synthetic stack.
        """
        refs_map = {}
        # Iterate all active refs output logic stripped for brevity.
        raw_refs = repo._run_git(['show-ref']).stdout.splitlines()
        for line in raw_refs:
            if not line:
                continue
            sha, ref = line.split(" ", 1)
            refs_map[ref] = sha
        self.logger.debug("Saved state with %s refs", len(refs_map))
        return refs_map

    def _restoreRepoState(self, repo: Repo, state: Dict[str, str]):
        """
        Restore packed-refs via manipulation after a failed stack.
        Re-applies the base state avoiding heavy disk checkouts.
        """
        self.logger.warning("Restoring repo state from checkpoint on failed speculative stack...")
        for ref, sha in state.items():
            try:
                repo._run_git(['update-ref', ref, sha])
            except GitCommandError:
                pass
        # Final cleanup safety
        repo._run_git(['reset', '--hard', 'HEAD'])

    def mergeChanges(self, items: List[SpeculativeMergeItem]) -> Dict[str, str]:
        """
        The Speculative Merge Engine.
        Executes a sequence of merges synchronously tagging the final status.
        If PRI -> PR2 fails, rolls back PRI state.
        Returns: {repo_name: synthetic_tag_ref}
        """
        # Dictionary storing where we got successfully
        synthetic_hash_map = {}
        state_checkpoints = {}

        self.logger.info("Starting Speculative Merge Stack (%s items)", len(items))
        try:
            for item in items:
                repo = self._get_repo(item.target_repo_url, item.repo_name)
                
                # Checkpoint the repository BEFORE any merge
                state_checkpoints[item.repo_name] = self._saveRepoState(repo)
                
                # Perform state hygiene to lock back to the remote cleanly
                repo.reset_state_hygiene(item.base_branch)

                # Execute merge strategy natively via FETCH_HEAD
                commit_hash = repo.merge_patchset(item.patchset_ref, strategy=item.strategy)
                
                # Crucial Step: Tag the resulting synthetic commit to avoid GC pruning
                # This exposes refs/zuul/... that external CI executors can fetch!
                synthetic_tag = f"refs/torri/{item.patchset_ref.replace('/','_')}_{uuid.uuid4().hex[:8]}"
                repo._run_git(['update-ref', synthetic_tag, commit_hash])
                
                self.logger.info("Created synthetic branch state %s at %s", synthetic_tag, commit_hash)
                synthetic_hash_map[item.repo_name] = synthetic_tag

        except GitCommandError as e:
            self.logger.error("Speculative stack collapsed during merge: %s", e)
            # Cascade rollback via checkpoints
            for r_name, checkpoint in state_checkpoints.items():
                self._restoreRepoState(self.repos[r_name], checkpoint)
            raise  # Hand back conflict to KafkConsumerWorker

        return synthetic_hash_map

