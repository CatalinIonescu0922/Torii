# Torri

Torri is a containerized CI platform for managing Gerrit-backed workflows and the supporting services around them. The repository is organized around Docker Compose, and the whole stack runs in containers.

## Requirements

- Docker
- Docker Compose

## Start and Stop

All project lifecycle commands are handled from the `compose/` folder.

```bash
cd compose
./launch.sh -s
```

This starts a fresh environment.

To stop the stack and remove its data/log volumes:

```bash
cd compose
./launch.sh -d
```

## Project Layout

- `compose/` - Docker Compose stack, launcher script, and container configuration
- `compose/files/` - service configuration and generated runtime files
- `microservices/` - Python services such as the executor, shared library, and Torri backend
- `web/` - frontend application

The Compose stack is split across smaller service definitions such as `gerrit.yaml`, `kafka.yaml`, `redis.yaml`, `server.yaml`, `web.yaml`, and `nginx.yaml`, with `compose.yaml` combining them into the full environment.

## Configuration Files

The Torri CI configuration lives in `compose/files/torri/`:

- `projects.yaml` - defines which repositories Torri watches and which jobs run on each pipeline
- `pipelines.yaml` - defines the check and gate pipelines, triggers, and success or failure behavior
- `jobs.yaml` - lists the jobs Torri can run, including timeouts and playbook paths
- `nodesets.yaml` - defines the available execution nodes and their labels

These files describe the CI behavior without requiring any local service setup.

## Notes

- The stack is fully containerized; no local service installation is required beyond Docker and Docker Compose.
- `compose/launch.sh` also supports `-r` for restart and `-h` for help.