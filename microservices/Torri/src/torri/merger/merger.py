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
    def __init__(self, target_repo_url: str, repo_name: str, base_branch: str, patchset_ref: str, strategy: str = "merge", index: int = 0):
        self.target_repo_url = target_repo_url
        self.repo_name = repo_name
        self.base_branch = base_branch
        self.patchset_ref = patchset_ref
        self.strategy = strategy
        self.index = index  # Track original order in patchset_refs list

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
        try:
            result = repo._run_git(['show-ref'], check=False)
            if result.returncode != 0:
                self.logger.warning("show-ref failed (repo may be empty): %s", result.stderr)
                return refs_map
            raw_refs = result.stdout.splitlines()
            for line in raw_refs:
                if not line:
                    continue
                sha, ref = line.split(" ", 1)
                refs_map[ref] = sha
            self.logger.debug("Saved state with %s refs", len(refs_map))
        except Exception as e:
            self.logger.error("Failed to save repo state: %s", e)
            raise
        return refs_map

    def _restoreRepoState(self, repo: Repo, state: Dict[str, str]):
        """
        Restore packed-refs via manipulation after a failed stack.
        Re-applies the base state avoiding heavy disk checkouts.
        """
        if not state:
            # Repo had no commits when the checkpoint was taken (e.g. first fetch failed).
            # There is nothing to restore - skip entirely to avoid operating on an empty repo.
            return
        self.logger.warning("Restoring repo state from checkpoint on failed speculative stack...")
        for ref, sha in state.items():
            try:
                repo._run_git(['update-ref', ref, sha])
            except GitCommandError:
                pass
        try:
            repo._run_git(['reset', '--hard', 'HEAD'])
        except GitCommandError:
            self.logger.warning("reset --hard HEAD failed after state restore - repo may be in inconsistent state")

    def mergeChanges(self, items: List[SpeculativeMergeItem]) -> Dict[str, str]:
        """
        The Speculative Merge Engine.
        Executes a sequence of merges synchronously tagging the final status.
        For same job (same target_repo_url): refs are STACKED on top of each other
        For different jobs (different target_repo_url): each gets SEPARATE env starting from origin/base_branch
        If any merge fails, rolls back ALL changes via checkpoints.
        Returns: {repo_name: synthetic_tag_ref}
        """
        # Dictionary storing where we got successfully
        synthetic_hash_map = {}
        state_checkpoints = {}

        # Group items by target_repo_url (same job vs separate jobs)
        from collections import defaultdict
        items_by_repo = defaultdict(list)
        for item in items:
            items_by_repo[item.target_repo_url].append(item)

        self.logger.info("Starting Speculative Merge Stack (%s items, %s unique repos)", len(items), len(items_by_repo))
        
        try:
            # Process each repository separately
            for target_repo_url, repo_items in items_by_repo.items():
                repo = self._get_repo(target_repo_url, repo_items[0].repo_name)
                repo_name = repo_items[0].repo_name
                
                self.logger.debug("Items before sort: %s", [(item.patchset_ref, item.index) for item in repo_items])
                
                # Checkpoint ONCE for this repo (before any merges in this group)
                state_checkpoints[repo_name] = self._saveRepoState(repo)
                
                # RESET ONCE at the start for this job - establishes base from origin
                base_branch = repo_items[0].base_branch
                repo.reset_state_hygiene(base_branch)
                self.logger.info("Stacking %d refs on %s (starting from origin/%s)", len(repo_items), repo_name, base_branch)
                
                # Ensure refs are processed in EXACT original order (left-to-right)
                # Sort by index which tracks position in the original patchset_refs list
                ordered_items = sorted(repo_items, key=lambda x: x.index)
                self.logger.debug("Items after sort: %s", [(item.patchset_ref, item.index) for item in ordered_items])
                self.logger.debug("Processing %d items in order: %s", len(ordered_items), [item.patchset_ref for item in ordered_items])
                
                # Now stack all refs from this job ON TOP of each other
                final_hash = None
                for idx, item in enumerate(ordered_items):
                    # First ref detaches to origin/base_branch, subsequent refs stack ON TOP
                    detach_first = (idx == 0)
                    self.logger.info("Applying ref %d/%d: %s (strategy=%s)", idx+1, len(ordered_items), item.patchset_ref, item.strategy)
                    final_hash = repo.merge_patchset(item.patchset_ref, strategy=item.strategy, base_branch=base_branch, detach_to_base=detach_first)
                    self.logger.debug("Stacked ref %d/%d: %s -> %s", idx+1, len(repo_items), item.patchset_ref, final_hash)
                    
                    # Create intermediate synthetic ref for debugging (optional, but useful)
                    # This allows tracking individual refs in the stack
                    intermediate_tag = f"refs/torri/{item.patchset_ref.replace('/','_')}_{uuid.uuid4().hex[:8]}"
                    repo._run_git(['update-ref', intermediate_tag, final_hash])
                    self.logger.debug("Intermediate synthetic ref: %s -> %s", intermediate_tag, final_hash)
                
                # Create FINAL synthetic ref for the entire stacked result
                # All refs in the job are represented by this single final hash
                stack_tag = f"refs/torri/{base_branch}_stack_{uuid.uuid4().hex[:8]}"
                repo._run_git(['update-ref', stack_tag, final_hash])
                
                self.logger.info("Final stacked result for job (repo=%s): %s -> %s", repo_name, stack_tag, final_hash)
                synthetic_hash_map[repo_name] = stack_tag

        except GitCommandError as e:
            self.logger.error("Speculative stack collapsed during merge: %s", e)
            # Cascade rollback via checkpoints
            for r_name, checkpoint in state_checkpoints.items():
                self._restoreRepoState(self.repos[r_name], checkpoint)
            raise  # Hand back conflict to KafkaConsumerWorker

        return synthetic_hash_map

