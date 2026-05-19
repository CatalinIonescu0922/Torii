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

import redis as redis_lib

from executor.ansible_runner import run_playbook
from executor.config import ExecutorConfig
from executor.log_relay import LogRelay
from executor.runners.base import BaseRunner
from executor.runners.docker_runner import DockerRunner
from executor.runners.ssh_runner import SshRunner
from executor.node_pool import NodePool

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
        self.merger_base_url = payload["merger_base_url"].rstrip("/")
        self.job_config = payload.get("job_config", {})
        self.nodeset_config = payload.get("nodeset_config", {})

        self.job_dir = os.path.join(config.job_dir, self.job_uuid)
        self.log = LogRelay(self.job_uuid, config.redis_url)

        self._node_pool: NodePool | None = None

    def run(self) -> None:
        try:
            succeeded = self._execute()
        except Exception as e:
            logger.error("Unexpected error in job %s: %s", self.job_uuid, e, exc_info=True)
            self.log.write(f"FATAL: {e}")
            succeeded = False
        finally:
            self.log.write_eof()
            self.semaphore.release()

        self._publish_result(succeeded)

    def _execute(self) -> bool:
        self._setup_job_dir()
        self._clone_project()

        runner = self._make_runner()
        try:
            runner.acquire(self.job_uuid)
        except RuntimeError as e:
            self.log.write(f"ERROR: {e}")
            return False

        try:
            self._write_inventory(runner)
            self._write_ansible_cfg(runner)
            return self._run_playbooks()
        finally:
            runner.release()
            self._cleanup_job_dir()

    def _setup_job_dir(self) -> None:
        os.makedirs(os.path.join(self.job_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.job_dir, "playbooks"), exist_ok=True)
        os.makedirs(os.path.join(self.job_dir, "ansible"), exist_ok=True)
        self.log.write(f"Job directory: {self.job_dir}")

    def _clone_project(self) -> None:
        repo_url = f"{self.merger_base_url}/{self.project}"
        src_dir = os.path.join(self.job_dir, "src")
        self.log.write(f"Cloning {repo_url} ref={self.synthetic_ref}")

        result = subprocess.run(
            ["git", "clone", "--depth=1", repo_url, src_dir],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")

        # Fetch and checkout the specific synthetic ref.
        subprocess.run(
            ["git", "-C", src_dir, "fetch", "origin", self.synthetic_ref],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "-C", src_dir, "checkout", "FETCH_HEAD"],
            capture_output=True,
            check=True,
        )
        self.log.write("Clone complete")

    def _make_runner(self) -> BaseRunner:
        nodes = self.nodeset_config.get("nodes", [])
        if not nodes:
            raise RuntimeError("nodeset has no nodes")

        # Only the first node is used for now (single-node nodesets cover most cases).
        node = nodes[0]
        label = node.get("label", "")
        node_name = node.get("name", "builder")

        # Try Docker first: if the label maps to a Docker image, use DockerRunner.
        image = self.config.get_image_for_label(label)
        if image:
            return DockerRunner(node_name=node_name, image=image)

        # Fall back to SSH runner from the node pool.
        if self._node_pool is None:
            self._node_pool = NodePool(self.config.nodes_config, self.config.redis_url)

        if not self._node_pool.has_label(label):
            raise RuntimeError(f"No runner available for label={label}")

        return SshRunner(node_name=node_name, label=label, pool=self._node_pool)

    def _write_inventory(self, runner: BaseRunner) -> None:
        inventory_path = os.path.join(self.job_dir, "ansible", "inventory")
        with open(inventory_path, "w") as f:
            f.write("[job_nodes]\n")
            f.write(runner.inventory_line() + "\n")

    def _write_ansible_cfg(self, runner: BaseRunner) -> None:
        cfg_path = os.path.join(self.job_dir, "ansible", "ansible.cfg")
        extras = runner.ansible_cfg_extras()
        with open(cfg_path, "w") as f:
            f.write("[defaults]\n")
            f.write(f"inventory = {os.path.join(self.job_dir, 'ansible', 'inventory')}\n")
            f.write(f"roles_path = {os.path.join(self.job_dir, 'src', 'roles')}\n")
            f.write("host_key_checking = False\n")
            if extras:
                f.write(extras)

    def _run_playbooks(self) -> bool:
        inventory = os.path.join(self.job_dir, "ansible", "inventory")
        ansible_cfg = os.path.join(self.job_dir, "ansible", "ansible.cfg")
        timeout = self.job_config.get("timeout", 600)

        phases = []
        if self.job_config.get("pre-run"):
            phases.append(("pre-run", self.job_config["pre-run"]))
        phases.append(("run", self.job_config.get("run", "")))
        if self.job_config.get("post-run"):
            phases.append(("post-run", self.job_config["post-run"]))

        for phase_name, playbook_ref in phases:
            playbooks = [playbook_ref] if isinstance(playbook_ref, str) else playbook_ref
            for playbook in playbooks:
                playbook_path = os.path.join(self.job_dir, "src", playbook)
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

                if rc != 0:
                    self.log.write(f"FAILED: {phase_name} exited with code {rc}")
                    # post-run always runs even after failure.
                    if phase_name != "post-run":
                        self._run_post_run_on_failure(inventory, ansible_cfg, timeout)
                    return False

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

    def _publish_result(self, succeeded: bool) -> None:
        status = "success" if succeeded else "failure"
        self.log.write(f"Job finished: {status}")
        logger.info("Job %s finished: %s", self.job_uuid, status)

        try:
            from confluent_kafka import Producer

            producer = Producer({"bootstrap.servers": self.config.kafka_bootstrap})
            result_payload = json.dumps({
                "job_uuid": self.job_uuid,
                "buildset_uuid": self.buildset_uuid,
                "job_name": self.job_name,
                "status": status,
            })
            producer.produce(
                JOB_RESULTS_TOPIC,
                key=self.job_uuid.encode(),
                value=result_payload.encode(),
            )
            producer.flush()

        except Exception as e:
            logger.error("Failed to publish job result for %s: %s", self.job_uuid, e, exc_info=True)
