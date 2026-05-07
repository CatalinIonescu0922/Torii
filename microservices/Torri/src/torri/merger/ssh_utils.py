import os
import paramiko
from urllib.parse import urlparse
from shared.logger_setup import get_logger

logger = get_logger("torri.merger.ssh")

def ensure_known_hosts(repo_url: str):
    """
    Dynamically builds the known_hosts file using Paramiko before attempting git clone 
    to ensure SSH verification is safe but allows first-time connections without prompt.
    """
    if not repo_url.startswith("ssh://") and not "@" in repo_url:
        return # Not SSH

    try:
        # Basic parsing: 'ssh://user@host:port/repo' or 'user@host:repo'
        if "://" in repo_url:
            parsed = urlparse(repo_url)
            hostname = parsed.hostname
            port = parsed.port or 22
        else:
            host_part = repo_url.split(":", 1)[0]
            if "@" in host_part:
                hostname = host_part.split("@")[1]
            else:
                hostname = host_part
            port = 22

        ssh_folder = os.path.expanduser("~/.ssh")
        os.makedirs(ssh_folder, exist_ok=True)
        known_hosts_file = os.path.join(ssh_folder, "known_hosts")

        client = paramiko.SSHClient()
        client.load_system_host_keys(known_hosts_file)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Perform a dummy connect just to cache the host key safely
        # It's expected to fail auth, but the host key will be added.
        try:
            client.connect(hostname, port=port, username="dummy", timeout=5)
        except paramiko.AuthenticationException:
            pass # We just wanted the host key
        except Exception as e:
            logger.debug(f"SSH key cache dummy connect failed (expected): {e}")
        finally:
            client.close()
            
    except Exception as e:
        logger.warning(f"Could not pre-cache SSH known_hosts for {repo_url}: {e}")
