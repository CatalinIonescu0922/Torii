"""
SSH runner.

Claims a VM from the node pool for the job.  Ansible connects via SSH.
ControlMaster multiplexing and pipelining reduce per-task SSH overhead.
"""

import logging

from executor.runners.base import BaseRunner
from executor.node_pool import NodePool

logger = logging.getLogger("executor.runners.ssh")


class SshRunner(BaseRunner):
    def __init__(self, node_name: str, label: str, pool: NodePool):
        self.node_name = node_name
        self.label = label
        self.pool = pool
        self._vm = None  # populated by acquire()

    def acquire(self, job_uuid: str) -> None:
        self._vm = self.pool.claim(label=self.label, job_uuid=job_uuid)
        if self._vm is None:
            raise RuntimeError(f"No available VM for label={self.label}")
        logger.info(
            "Claimed VM hostname=%s label=%s for job=%s",
            self._vm["hostname"], self.label, job_uuid,
        )

    def release(self) -> None:
        if self._vm:
            self.pool.release(self._vm["hostname"])
            logger.info("Released VM hostname=%s", self._vm["hostname"])
            self._vm = None

    def inventory_line(self) -> str:
        return (
            f"{self.node_name} "
            f"ansible_host={self._vm['hostname']} "
            f"ansible_user={self._vm.get('username', 'torii')} "
            f"ansible_connection=ssh"
        )

    def ansible_cfg_extras(self) -> str:
        # ControlMaster keeps the SSH connection alive between tasks.
        # pipelining skips a separate sftp call per task module upload.
        return (
            "[ssh_connection]\n"
            "ssh_args = -o ControlMaster=auto -o ControlPersist=60s\n"
            "pipelining = True\n"
        )
