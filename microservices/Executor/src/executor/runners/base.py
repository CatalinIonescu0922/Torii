"""
Abstract runner interface.

A runner allocates a machine (container or VM) for a job, generates the
Ansible inventory entry for it, and releases it when the job is done.
"""

from abc import ABC, abstractmethod


class BaseRunner(ABC):
    """One runner manages one node from a nodeset."""

    @abstractmethod
    def acquire(self, job_uuid: str) -> None:
        """Allocate the node. Blocks until the node is ready."""

    @abstractmethod
    def release(self) -> None:
        """Free the node after the job finishes (or fails)."""

    @abstractmethod
    def inventory_vars(self) -> dict:
        """
        Return the Ansible inventory variables for this node as a dictionary.
        Example:
            {"ansible_host": "torii-...", "ansible_connection": "docker", "ansible_user": "root"}
        """

    @abstractmethod
    def ansible_cfg_extras(self) -> str:
        """
        Extra lines to append to ansible.cfg for this runner type.
        Return an empty string if nothing extra is needed.
        """
