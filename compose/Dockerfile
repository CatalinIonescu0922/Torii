# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:latest
ARG DOCKER_CLI_IMAGE=docker:27-cli


# ==========================================
# Tool Sources
# ==========================================
FROM ${UV_IMAGE} AS uv-source
FROM ${DOCKER_CLI_IMAGE} AS docker-cli-source


# ==========================================
# Common Python Builder
# ==========================================
FROM ${PYTHON_IMAGE} AS builder

COPY --link --from=uv-source /uv /uvx /bin/

ENV PATH="/opt/venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /build

RUN uv venv /opt/venv
COPY microservices/Shared/ /build/Shared/
COPY microservices/Torri/ /build/Torri/
COPY microservices/Executor/ /build/Executor/

RUN uv pip install --no-cache supervisor ./Shared ./Torri ./Executor


# ==========================================
# Shared Runtime Base
# ==========================================
FROM ${PYTHON_IMAGE} AS runtime-base

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/Shared/src:/app/Torri/src:/app/Executor/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --link --from=uv-source /uv /uvx /bin/
COPY --link --from=builder /opt/venv /opt/venv
COPY --link microservices/Shared/ /app/Shared/
COPY --link microservices/Torri/ /app/Torri/
COPY --link microservices/Executor/ /app/Executor/
COPY --link microservices/Torri/src/torri/config/log/ /app/config/log/

RUN mkdir -p \
    /app/ephemeral/logs \
    /app/logs \
    /etc/supervisor/conf.d \
    /var/log/supervisor \
    /var/run && \
    printf '%s\n' \
        '[supervisord]' \
        'nodaemon=true' \
        '' \
        '[include]' \
        'files=/etc/supervisor/conf.d/*.conf' \
        > /etc/supervisor/supervisord.conf

CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]


# ==========================================
# Merger Service
# ==========================================
FROM runtime-base AS merger

RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-server && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/run/sshd

COPY --link compose/files/ssh/ /home/git/.ssh/
COPY --link compose/files/supervisor/merger/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN useradd -o -u 0 -g 0 -m -d /home/git -s /usr/bin/git-shell git && \
    mkdir -p /home/git/.ssh /tmp/torri_workspaces && \
    chmod 700 /home/git/.ssh && \
    chmod 600 /home/git/.ssh/Torri_ed25519 && \
    ssh-keygen -A && \
    rm -rf /root/.ssh && \
    ln -s /home/git/.ssh /root/.ssh && \
    git config --global user.email "torii@localdomain" && \
    git config --global user.name "Torii Merger"

EXPOSE 22


# ==========================================
# Scheduler Service
# ==========================================
FROM runtime-base AS scheduler

COPY --link compose/files/supervisor/scheduler/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --link compose/files/supervisor/scheduler/status_api.conf /etc/supervisor/conf.d/status_api.conf
COPY --link compose/files/torri/ /app/Torri/src/torri/config/layout/


# ==========================================
# Executor Service
# ==========================================
FROM runtime-base AS executor

COPY --link --from=docker-cli-source /usr/local/bin/docker /usr/local/bin/docker
COPY --link compose/files/supervisor/executor/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --link microservices/Executor/src/executor/executor.conf /app/Executor/src/executor/executor.conf
COPY --link compose/files/ssh/Torri_ed25519 /root/.ssh/Torri_ed25519
COPY --link compose/files/ssh/config /root/.ssh/config
COPY --link compose/files/jobs/ /app/jobs/

RUN chmod 700 /root/.ssh && \
    chmod 600 /root/.ssh/Torri_ed25519 && \
    mkdir -p /var/torii/jobs /etc/torri
