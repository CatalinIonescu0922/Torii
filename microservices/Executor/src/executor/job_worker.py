"""
Job worker.

Runs one job end-to-end:
  1. Set up a scratch directory under job_dir/{job_uuid}/
  2. Clone the project at the synthetic ref from the merger.
  3. Acquire a runner (Docker container or SSH VM).
  4. Write the Ansible inventory and ansible.cfg.
  5. Run pre-run playbook(s), then run, then post-run.
  6. Publish the result to the job-results Kafka topic.
  7. Clean up.

All log output is written to LogRelay (Redis) in real time so the UI can
stream it while the job is running.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

import redis as redis_lib

from executor.ansible_runner import run_playbook
from executor.config import ExecutorConfig
from executor.log_relay import LogRelay
from executor.runners.base import BaseRunner
from executor.runners.docker_runner import DockerRunner
from executor.runners.ssh_runner import SshRunner
from executor.node_pool import NodePool
from confluent_kafka import Producer
from pathlib import Path


logger = logging.getLogger("executor.job_worker")

JOB_RESULTS_TOPIC = "job-results"


class JobWorker:
    def __init__(self, config: ExecutorConfig, payload: dict, semaphore: threading.Semaphore):
        self.config = config
        self.payload = payload
        self.semaphore = semaphore

        self.job_uuid = payload["job_uuid"]
        self.buildset_uuid = payload["buildset_uuid"]
        self.job_name = payload["job_name"]
        self.project = payload["project"]
        self.branch = payload["branch"]
        self.synthetic_ref = payload["synthetic_ref"]
        self.job_config = payload.get("job_config", {})
        self.nodeset_config = payload.get("nodeset_config", {})

        self.job_dir = os.path.join(config.job_dir, self.job_uuid)
        self.log = LogRelay(self.job_uuid, config.redis_url)

        self._node_pool: NodePool | None = None
        self.started_at: datetime | None = None
        self.started_monotonic: float | None = None

    def run(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.started_monotonic = time.perf_counter()
        self._publish_result("running")
        try:
            if (self._execute()):
                self._publish_result("success")
            else:
                self._publish_result("failure")
        except Exception as e:
            logger.error("Unexpected error in job %s: %s", self.job_uuid, e, exc_info=True)
            self.log.write(f"FATAL: {e}")
            self._publish_result("failure")
        finally:
            self.log.write_eof()
            self.semaphore.release()

    def _execute(self) -> bool:
        logger.info("[JOB] Starting execution for job_uuid=%s buildset=%s project=%s", self.job_uuid, self.buildset_uuid, self.project)
        self._setup_job_dir()
        logger.info("[JOB] Job directory created at %s", self.job_dir)
        
        self._clone_project()
        logger.info("[JOB] Project cloned successfully at synthetic_ref=%s", self.synthetic_ref)
        
        self._inject_playbooks()
        logger.info("[JOB] Playbooks injected into project")

        logger.info("[JOB] Creating runner with nodeset_config=%s", self.nodeset_config)
        runner = self._make_runner()
        logger.info("[JOB] Runner created: type=%s", type(runner).__name__)
        
        try:
            logger.info("[JOB] Acquiring runner (container/node) for execution")
            runner.acquire(self.job_uuid)
            logger.info("[JOB] Runner acquired successfully")
        except RuntimeError as e:
            logger.error("[JOB] Failed to acquire runner: %s", e)
            self.log.write(f"ERROR: {e}")
            return False

        try:
            logger.info("[JOB] Writing Ansible inventory and config")
            self._write_inventory(runner)
            self._write_ansible_cfg(runner)
            logger.info("[JOB] Inventory and config written, starting playbooks")
            success = self._run_playbooks()
            logger.info("[JOB] Playbooks completed with success=%s", success)
            return success
        finally:
            logger.info("[JOB] Releasing runner")
            runner.release()
            logger.info("[JOB] Runner released, cleaning up job directory")
            self._cleanup_job_dir()
            logger.info("[JOB] Job execution completed")

    def _setup_job_dir(self) -> None:
        os.makedirs(os.path.join(self.job_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.job_dir, "src", "playbooks"), exist_ok=True)
        os.makedirs(os.path.join(self.job_dir, "ansible"), exist_ok=True)
        self.log.write(f"Job directory: {self.job_dir}")

    def _clone_project(self) -> None:
        repo_name = self.project.split("/")[-1].replace(".git", "")
        repo_path = f"{self.config.merger_workspace_path}/{repo_name}"
        merger_url = f"ssh://{self.config.merger_user}@{self.config.merger_host}:{self.config.merger_port}{repo_path}"
        src_dir = os.path.join(self.job_dir, "src")
        
        logger.info("[CLONE] Fetching from merger: url=%s ref=%s", merger_url, self.synthetic_ref)
        self.log.write(f"Fetching {merger_url} ref={self.synthetic_ref}")

        env = os.environ.copy()
        env['GIT_SSH_COMMAND'] = f"ssh -i {self.config.merger_ssh_key} -o StrictHostKeyChecking=no"

        # Init an empty repo and fetch only the exact synthetic ref the merger
        # prepared. This avoids downloading the default branch first and then
        # fetching on top — one round-trip, one commit.
        logger.debug("[CLONE] Running git init \"% s\"", src_dir)
        subprocess.run(["git", "init", src_dir], capture_output=True, check=True)

        logger.debug("[CLONE] Running git fetch from merger...")
        result = subprocess.run(
            ["git", "-C", src_dir, "fetch", "--depth=1", merger_url, self.synthetic_ref],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            logger.error("[CLONE] Git fetch FAILED with returncode=%d", result.returncode)
            logger.error("[CLONE] stderr: %s", result.stderr[:500])
            logger.error("[CLONE] stdout: %s", result.stdout[:500])
            raise RuntimeError(f"git fetch failed: {result.stderr.strip()}")

        logger.debug("[CLONE] Running git checkout FETCH_HEAD")
        subprocess.run(
            ["git", "-C", src_dir, "checkout", "FETCH_HEAD"],
            capture_output=True,
            check=True,
            env=env,
        )
        logger.info("[CLONE] Successfully fetched and checked out project at %s", src_dir)
        self.log.write("Fetch complete")

    def _inject_playbooks(self) -> None:
        """Copy job-specific playbooks from image into cloned project."""
        # Jobs are stored in /app/jobs/{job_name}/ in the image.
        # We copy the entire job directory to {job_dir}/src/playbooks/{job_name}/
        # so that job_config.run paths like "playbooks/check-syntax/run.yaml" resolve correctly.
        source_job = f"/app/jobs/{self.job_name}"
        dest_playbooks = os.path.join(self.job_dir, "src", "playbooks", self.job_name)
        
        logger.info("[INJECT] Attempting to inject playbooks for job=%s: source=%s dest=%s", self.job_name, source_job, dest_playbooks)
        
        if os.path.isdir(source_job):
            try:
                logger.info("[INJECT] Source job directory exists, copying playbooks...")
                shutil.copytree(source_job, dest_playbooks, dirs_exist_ok=True)
                logger.info("[INJECT] Successfully injected playbooks for job %s from %s", self.job_name, source_job)
                self.log.write(f"Injected playbooks for job {self.job_name} from {source_job}")
            except Exception as e:
                logger.error("[INJECT] Failed to inject playbooks for job %s: %s", self.job_name, e, exc_info=True)
                self.log.write(f"WARNING: Failed to inject playbooks: {e}")
        else:
            logger.warning("[INJECT] Source job directory NOT FOUND: %s", source_job)
            self.log.write(f"WARNING: No playbooks found for job {self.job_name} at {source_job}")

    def _make_runner(self) -> BaseRunner:
        nodes = self.nodeset_config.get("nodes", [])
        logger.debug("[RUNNER] Nodeset has %d nodes", len(nodes))
        if not nodes:
            logger.error("[RUNNER] ERROR: nodeset_config has no nodes!")
            logger.error("[RUNNER] nodeset_config dump: %s", self.nodeset_config)
            raise RuntimeError("nodeset has no nodes")

        # Only the first node is used for now (single-node nodesets cover most cases).
        node = nodes[0]
        label = node.get("label", "")
        node_name = node.get("name", "builder")
        logger.info("[RUNNER] Using node_name=%s label=%s", node_name, label)

        # Try Docker first: if the label maps to a Docker image, use DockerRunner.
        image = self.config.get_image_for_label(label)
        if image:
            logger.info("[RUNNER] Found Docker image for label=%s: image=%s", label, image)
            return DockerRunner(
                node_name=node_name,
                image=image,
                source_dir=os.path.join(self.job_dir, "src"),
            )

        # Fall back to SSH runner from the node pool.
        logger.info("[RUNNER] No Docker image, trying SSH pool...")
        if self._node_pool is None:
            self._node_pool = NodePool(self.config.nodes_config, self.config.redis_url)

        if not self._node_pool.has_label(label):
            logger.error("[RUNNER] No SSH runner available for label=%s", label)
            raise RuntimeError(f"No runner available for label={label}")

        logger.info("[RUNNER] Found SSH runner for label=%s", label)
        return SshRunner(node_name=node_name, label=label, pool=self._node_pool)

    def _write_inventory(self, runner: BaseRunner) -> None:
        import yaml
        inventory_path = os.path.join(self.job_dir, "ansible", "inventory.yaml")
        
        # Build YAML inventory structure
        inventory_data = {
            "all": {
                "hosts": {
                    runner.node_name: runner.inventory_vars()
                }
            }
        }
        
        with open(inventory_path, "w") as f:
            yaml.dump(inventory_data, f, default_flow_style=False)

    def _write_ansible_cfg(self, runner: BaseRunner) -> None:
        action_plugins_path = Path(__file__).resolve().parent / "ansible_plugins" / "action"

        cfg_path = os.path.join(self.job_dir, "ansible", "ansible.cfg")
        extras = runner.ansible_cfg_extras()
        with open(cfg_path, "w") as f:
            f.write("[defaults]\n")
            f.write(f"inventory = {os.path.join(self.job_dir, 'ansible', 'inventory.yaml')}\n")
            f.write(f"roles_path = {os.path.join(self.job_dir, 'src', 'roles')}\n")
            f.write(f"action_plugins = {action_plugins_path}\n")
            f.write("host_key_checking = False\n")
            if extras:
                f.write(extras)

    def _run_playbooks(self) -> bool:
        inventory = os.path.join(self.job_dir, "ansible", "inventory.yaml")
        ansible_cfg = os.path.join(self.job_dir, "ansible", "ansible.cfg")
        timeout = self.job_config.get("timeout", 600)
        logger.info("[PLAYBOOK] Starting playbook execution timeout=%ds", timeout)
        logger.info("[PLAYBOOK] inventory=%s", inventory)
        logger.info("[PLAYBOOK] ansible_cfg=%s", ansible_cfg)
        logger.debug("[PLAYBOOK] job_config=%s", self.job_config)

        phases = []
        if self.job_config.get("pre-run"):
            phases.append(("pre-run", self.job_config["pre-run"]))
        phases.append(("run", self.job_config.get("run", "")))
        if self.job_config.get("post-run"):
            phases.append(("post-run", self.job_config["post-run"]))

        logger.info("[PLAYBOOK] Total phases to execute: %d", len(phases))
        for phase_name, playbook_ref in phases:
            playbooks = [playbook_ref] if isinstance(playbook_ref, str) else playbook_ref
            for playbook in playbooks:
                playbook_path = os.path.join(self.job_dir, "src", playbook)
                logger.info("[PLAYBOOK] Checking if playbook exists: %s", playbook_path)
                if not os.path.exists(playbook_path):
                    logger.error("[PLAYBOOK] PLAYBOOK FILE NOT FOUND: %s", playbook_path)
                    logger.error("[PLAYBOOK] Available files in job_dir: %s", os.listdir(self.job_dir) if os.path.exists(self.job_dir) else "job_dir missing")
                    self.log.write(f"ERROR: Playbook file not found: {playbook_path}")
                    return False
                
                logger.info("[PLAYBOOK] Executing %s: %s", phase_name, playbook)
                self.log.write(f"--- {phase_name}: {playbook} ---")

                rc = run_playbook(
                    playbook_path=playbook_path,
                    inventory_path=inventory,
                    ansible_cfg_path=ansible_cfg,
                    job_dir=self.job_dir,
                    use_bwrap=self.config.use_bwrap,
                    write_log=self.log.write,
                    timeout=timeout,
                )

                logger.info("[PLAYBOOK] Phase %s completed with rc=%d", phase_name, rc)
                if rc != 0:
                    logger.error("[PLAYBOOK] PHASE FAILED: %s", phase_name)
                    self.log.write(f"FAILED: {phase_name} exited with code {rc}")
                    # post-run always runs even after failure.
                    if phase_name != "post-run":
                        self._run_post_run_on_failure(inventory, ansible_cfg, timeout)
                    return False

        logger.info("[PLAYBOOK] All playbook phases completed successfully")
        return True

    def _run_post_run_on_failure(self, inventory, ansible_cfg, timeout) -> None:
        playbook_ref = self.job_config.get("post-run")
        if not playbook_ref:
            return
        playbooks = [playbook_ref] if isinstance(playbook_ref, str) else playbook_ref
        for playbook in playbooks:
            playbook_path = os.path.join(self.job_dir, "src", playbook)
            self.log.write(f"--- post-run (cleanup after failure): {playbook} ---")
            run_playbook(
                playbook_path=playbook_path,
                inventory_path=inventory,
                ansible_cfg_path=ansible_cfg,
                job_dir=self.job_dir,
                use_bwrap=self.config.use_bwrap,
                write_log=self.log.write,
                timeout=timeout,
            )

    def _cleanup_job_dir(self) -> None:
        try:
            shutil.rmtree(self.job_dir)
        except Exception as e:
            logger.warning("Could not clean up job dir %s: %s", self.job_dir, e)

    def _publish_result(self, status: str) -> None:
        if status == "running":
            self.log.write("Job started")
        else:
            self.log.write(f"Job finished: {status}")
        logger.info("Job %s finished: %s", self.job_uuid, status)

        try:
            producer = Producer({"bootstrap.servers": self.config.kafka_bootstrap})
            result = {
                "job_uuid": self.job_uuid,
                "buildset_uuid": self.buildset_uuid,
                "job_name": self.job_name,
                "status": status,
            }
            if self.started_at:
                result["start_time"] = self.started_at.isoformat()
            if status != "running":
                end_time = datetime.now(timezone.utc)
                result["end_time"] = end_time.isoformat()
                if self.started_monotonic is not None:
                    result["duration_seconds"] = round(time.perf_counter() - self.started_monotonic, 3)

            result_payload = json.dumps(result)
            producer.produce(
                JOB_RESULTS_TOPIC,
                key=self.job_uuid.encode(),
                value=result_payload.encode(),
            )
            producer.flush()

        except Exception as e:
            logger.error("Failed to publish job result for %s: %s", self.job_uuid, e, exc_info=True)
