"""
Docker runner.

Creates an ephemeral Docker container for the job.  Ansible uses the
docker connection plugin to exec tasks inside it.

Container lifecycle:
  acquire()  → docker run -d --name torii-{job_uuid}-{node_name} {image} sleep infinity
  release()  → docker rm -f {container_name}
"""

import logging
import subprocess

from executor.runners.base import BaseRunner

logger = logging.getLogger("executor.runners.docker")


class DockerRunner(BaseRunner):
    def __init__(self, node_name: str, image: str):
        self.node_name = node_name
        self.image = image
        self.container_name = ""

    def acquire(self, job_uuid: str) -> None:
        self.container_name = f"torii-{job_uuid}-{self.node_name}"
        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            self.image,
            "sleep", "infinity",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start container {self.container_name}: {result.stderr.strip()}"
            )
        logger.info("Container started: %s image=%s", self.container_name, self.image)

    def release(self) -> None:
        if not self.container_name:
            return
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
        )
        logger.info("Container removed: %s", self.container_name)

    def inventory_line(self) -> str:
        return (
            f"{self.node_name} "
            f"ansible_connection=docker "
            f"ansible_host={self.container_name} "
            f"ansible_user=root"
        )

    def ansible_cfg_extras(self) -> str:
        return ""
