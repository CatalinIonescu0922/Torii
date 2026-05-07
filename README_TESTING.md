# Testing Workflow & Verification Guide

## 1. How the Workflow Operates (The Big Picture)

When you are ready to test the system, the process follows these sequential steps:

1. **The Scheduler (`scheduler.py`)**: This is your manual trigger. When you run this script, it immediately generates mock `MergeRequest` payloads (representing different Gerrit patchsets to merge).
2. **Kafka Eventing (`merger-requests`)**: The scheduler pushes these payloads directly to the Kafka `merger-requests` topic. Kafka acts as the postal service, guaranteeing the messages are held until the merger is ready.
3. **The Merger Service (`torri-merger`)**: Running continuously in the background inside your Docker container (managed by `supervisord`), the merger listens to the `merger-requests` topic. 
4. **Execution & Git Operations**: Once the merger consumes a request, it uses the SSH keys (configured via Paramiko) to connect to Gerrit, fetches the requested patchsets into the isolated `refs/torri/` namespace, and attempts the merges. 
5. **Response (`merger-responses` / `merger-dlq`)**: 
   - If successful or if a Git conflict occurs, it outputs a `MergeResponse` to the `merger-responses` topic.
   - If the payload itself was corrupted or invalid, passing it triggers a Pydantic failure, routing it to the Dead Letter Queue (`merger-dlq`).

## 2. When Does the Scheduler Send the Request?

**Immediately.** 
The moment you execute the `scheduler.py` script manually, it connects to Kafka, produces the 10 messages, and finishes. It doesn't wait; it acts as a "fire-and-forget" mechanism. The merger service inside the container, assuming it is running, will pick up these messages almost instantly.

*Note: You run this from your host machine or inside a connected container:*
```bash
# Example of how you would trigger it (make sure your venv is active)
python microservices/Torri/cmd/scheduler.py
```

## 3. Where Do the Logs End Up Inside the Container?

Since the Merger microservice is run inside the Docker container by `supervisord` (acting as PID 1), the logs will go to a specific location depending on how Supervisor handles standard output. You have a few ways to check them:

**Method A: Quick Container Logs (Docker level)**
If Supervisor is configured to forward child process logs to standard output, you can see them directly from your host:
```bash
docker compose logs -f torri_runtime  # (or whatever your container name is in compose.yaml)
```

**Method B: Exploring inside the Container (Supervisor Logs)**
Supervisor automatically captures the `stdout` and `stderr` of the apps it runs and saves them to log files inside the container. 
To look at the exact log files:
1. Shell into the container:
   ```bash
   docker exec -it <container_name> bash
   ```
2. Check the Supervisor log directory (typically `/var/log/supervisor/`):
   ```bash
   ls -la /var/log/supervisor/
   ```
3. Tail the specific merger logs (the exact filename depends on your `.conf` naming):
   ```bash
   tail -f /var/log/supervisor/merger-stdout---supervisor-xxxx.log
   tail -f /var/log/supervisor/merger-stderr---supervisor-xxxx.log
   ```

**Method C: Ephemeral Logs (File-based)**
If your Python logger (`logger_setup.py` / `main_logging.yaml`) is configured to write to the `ephemeral/logs/` directory you created earlier, you can also check there:
```bash
cat /home/cata/Desktop/Torii/microservices/Torri/ephemeral/logs/merger.log
```

## 4. How to Verify Everything Worked Correctly

To be absolutely sure the pipeline processed the test flawlessly, look for these three indicators:

1. **Check the Merger Logs:**
   Read the Supervisor or Docker logs. You should see logs like:
   `[INFO] Consumed MergeRequest for project: infrastructure/terraform.git`
   `[INFO] Successfully fetched and merged 3 patchsets.`

2. **Inspect the Git Directory (`/tmp/torri_workspaces`):**
   Exec into the container and check the workspace. You should see Git folders that the merger created for the test.
   ```bash
   ls -la /tmp/torri_workspaces/
   ```
   If you check the git history inside one of those (`git log`), you'll see the synthetic `refs/torri/*` branches doing the work.

3. **Check the Kafka Output Topics:**
   Listen to the `merger-responses` target topic to see if the Merger processed the results back.
   ```bash
   # From inside your kafka container
   kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic merger-responses --from-beginning
   ```
   If it failed validation, listen to the DLQ:
   ```bash
   kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic merger-dlq --from-beginning
   ```
