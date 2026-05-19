"""
Node pool — Redis-backed claim/release for SSH VMs.

Nodes are loaded from nodes.yaml at startup and registered in Redis as
HSET entries.  A claim is a SETNX lock key.  A release DELetes it.

nodes.yaml format:
    nodes:
      - node:
          name: vm-01
          hostname: 192.168.1.100
          username: torii
          labels:
            - debian-bookworm
"""

import logging
import yaml

import redis as redis_lib

logger = logging.getLogger("executor.node_pool")

LOCK_KEY_PREFIX = "torri:node:lock:"
NODE_KEY_PREFIX = "torri:nodepool:vm:"
# Safety TTL: if the executor dies mid-job, the lock expires and the node is freed.
LOCK_TTL = 2 * 3600  # 2 hours


class NodePool:
    def __init__(self, nodes_config_path: str, redis_url: str):
        self._redis = redis_lib.from_url(redis_url, decode_responses=True)
        self._nodes: list[dict] = []
        self._load(nodes_config_path)

    def _load(self, path: str) -> None:
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("nodes.yaml not found at %s — SSH pool disabled", path)
            return

        for item in data.get("nodes", []):
            node = item.get("node", {})
            if not node.get("hostname"):
                continue
            self._nodes.append(node)
            self._redis.hset(
                f"{NODE_KEY_PREFIX}{node['hostname']}",
                mapping={
                    "name": node.get("name", node["hostname"]),
                    "hostname": node["hostname"],
                    "username": node.get("username", "torii"),
                    "labels": ",".join(node.get("labels", [])),
                },
            )

        logger.info("Node pool loaded %d VMs", len(self._nodes))

    def claim(self, label: str, job_uuid: str) -> dict | None:
        """
        Claim the first available VM with the given label.

        Uses SETNX so two executors racing for the same VM cannot both win.
        Returns the node dict on success, None if no node is available.
        """
        for node in self._nodes:
            if label not in node.get("labels", []):
                continue
            lock_key = f"{LOCK_KEY_PREFIX}{node['hostname']}"
            # SETNX returns True only if the key did not exist.
            acquired = self._redis.set(lock_key, job_uuid, nx=True, ex=LOCK_TTL)
            if acquired:
                return node
        return None

    def release(self, hostname: str) -> None:
        self._redis.delete(f"{LOCK_KEY_PREFIX}{hostname}")

    def has_label(self, label: str) -> bool:
        return any(label in n.get("labels", []) for n in self._nodes)
