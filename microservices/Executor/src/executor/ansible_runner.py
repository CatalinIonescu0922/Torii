"""
Ansible runner.

Runs ansible-playbook as a subprocess.  When use_bwrap=True the subprocess
is wrapped in bubblewrap (bwrap) to limit what the playbook can see:

  - /usr, /bin, /lib, /lib64    read-only (system executables and libs)
  - /proc, /dev, /tmp            standard pseudo-filesystems
  - /etc/resolv.conf, /etc/ssl   read-only (DNS and TLS needed by Ansible)
  - {job_dir}                    read-write (the only writable path)

bwrap uses unprivileged user namespaces — no root required.
Network access is NOT isolated because Ansible must reach target nodes.
The --unshare-pid flag gives the process its own PID namespace so it cannot
signal other jobs or see the host process list.

Lines are written to the caller-supplied write_log callable as they arrive,
allowing the log relay to forward them to Redis in real time.
"""

import logging
import os
import shutil
import subprocess
from typing import Callable

logger = logging.getLogger("executor.ansible_runner")


def run_playbook(
    playbook_path: str,
    inventory_path: str,
    ansible_cfg_path: str,
    job_dir: str,
    use_bwrap: bool,
    write_log: Callable[[str], None],
    timeout: int = 600,
) -> int:
    """
    Run ansible-playbook and stream output line by line to write_log.

    Returns the exit code.  Non-zero means the playbook failed.
    """
    ansible_bin = shutil.which("ansible-playbook")
    if not ansible_bin:
        write_log("ERROR: ansible-playbook not found in PATH")
        return 1

    env = {**os.environ, 
           "ANSIBLE_CONFIG": ansible_cfg_path,
           "PYTHONUNBUFFERED": "1",
           "ANSIBLE_CALLBACK_RESULT_FORMAT": "yaml",
           }

    ansible_cmd = [
        ansible_bin,
        "-i", inventory_path,
        playbook_path,
    ]

    if use_bwrap:
        cmd = _wrap_in_bwrap(ansible_cmd, job_dir)
    else:
        cmd = ansible_cmd

    logger.info("[ANSIBLE] Starting playbook with inventory path : %s %s", playbook_path, inventory_path)
    logger.debug("[ANSIBLE] Running: %s", " ".join(cmd[:5]))
    write_log(f"Running playbook: {playbook_path}")

    try:
        logger.debug("[ANSIBLE] Spawning subprocess")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        logger.info("[ANSIBLE] Process started with pid=%d", proc.pid)
        
        line_count = 0
        for line in proc.stdout:
            line_count += 1
            write_log(line.rstrip("\n"))
        
        proc.wait(timeout=timeout)
        logger.info("[ANSIBLE] Playbook completed: returncode=%d output_lines=%d", proc.returncode, line_count)
        return proc.returncode

    except subprocess.TimeoutExpired:
        logger.error("[ANSIBLE] Playbook TIMEOUT after %ds - killing process", timeout)
        proc.kill()
        write_log(f"ERROR: playbook timed out after {timeout}s")
        return 1

    except Exception as e:
        logger.error("[ANSIBLE] Exception in run_playbook: %s", e, exc_info=True)
        write_log(f"ERROR: {e}")
        return 1


def _wrap_in_bwrap(ansible_cmd: list, job_dir: str) -> list:
    """
    Wrap ansible_cmd in a bwrap user namespace sandbox.

    The sandbox mounts system directories read-only and job_dir read-write.
    The Ansible process cannot access other job directories, host credentials,
    or the host process list.
    """
    bwrap_bin = shutil.which("bwrap")
    if not bwrap_bin:
        logger.warning("bwrap not found — running ansible-playbook without sandbox")
        return ansible_cmd

    mounts = []

    # Mount system directories read-only.
    for path in ["/usr", "/bin", "/sbin", "/lib", "/lib64"]:
        if os.path.exists(path):
            mounts += ["--ro-bind", path, path]

    # Symlinks some distros use (e.g. /lib → /usr/lib).
    for src, dst in [("/usr/lib", "/lib"), ("/usr/lib64", "/lib64"), ("/usr/bin", "/bin")]:
        if os.path.islink(dst):
            mounts += ["--symlink", src, dst]

    # Pseudo-filesystems.
    mounts += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]

    # DNS and TLS certificates so Ansible can reach remote hosts.
    for path in ["/etc/resolv.conf", "/etc/ssl/certs"]:
        if os.path.exists(path):
            mounts += ["--ro-bind", path, path]

    # The job directory is the only writable path.
    mounts += ["--bind", job_dir, job_dir]

    return [
        bwrap_bin,
        *mounts,
        "--chdir", job_dir,
        "--unshare-pid",
        "--die-with-parent",
        "--",
        *ansible_cmd,
    ]
