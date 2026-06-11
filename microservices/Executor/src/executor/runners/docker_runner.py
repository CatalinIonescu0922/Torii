"""
Docker runner.

Creates an ephemeral Docker container for the job.  Ansible uses the
docker connection plugin to exec tasks inside it.

Container lifecycle:
    acquire()  → docker run -d --mount source checkout --name torii-{job_uuid}-{node_name} {image} sleep infinity
  release()  → docker rm -f {container_name}
"""

import logging
import subprocess

from executor.runners.base import BaseRunner

logger = logging.getLogger("executor.runners.docker")


class DockerRunner(BaseRunner):
    def __init__(self, node_name: str, image: str, source_dir: str):
        self.node_name = node_name
        self.image = image
        self.source_dir = source_dir
        self.container_name = ""

    def acquire(self, job_uuid: str) -> None:
        self.container_name = f"torii-{job_uuid}-{self.node_name}"
        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--mount", f"type=bind,source={self.source_dir},target={self.source_dir}",
            "--workdir", self.source_dir,
            self.image,
            "sleep", "infinity",
        ]
        logger.info(
            "[DOCKER] Executing docker run: image=%s container=%s source_dir=%s",
            self.image, self.container_name, self.source_dir,
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("[DOCKER] docker run failed: returncode=%d", result.returncode)
            logger.error("[DOCKER] stderr: %s", result.stderr[:500])
            raise RuntimeError(
                f"Failed to start container {self.container_name}: {result.stderr.strip()}"
            )
        container_id = result.stdout.strip()
        logger.info("[DOCKER] Container acquired: id=%s name=%s", container_id[:12], self.container_name)

    def release(self) -> None:
        if not self.container_name:
            logger.debug("[DOCKER] No container to release")
            return
        logger.info("[DOCKER] Releasing container: %s", self.container_name)
        result = subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning("[DOCKER] docker rm returned code %d: %s", result.returncode, result.stderr[:200])
        else:
            logger.info("[DOCKER] Container released successfully: %s", self.container_name)

    def inventory_vars(self) -> dict:
        variables = {
            "ansible_connection": "docker",
            "ansible_host": self.container_name,
            "ansible_user": "root",
            "torii_src_dir": self.source_dir,
        }
        logger.debug("[DOCKER] Inventory vars: %s", variables)
        return variables

    def ansible_cfg_extras(self) -> str:
        return ""
