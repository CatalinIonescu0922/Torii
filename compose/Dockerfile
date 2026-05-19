# ==========================================
# Stage 1: Common Builder
# ==========================================
FROM python:3.12-slim AS builder

# Install uv directly from the official astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y build-essential

# We use uv to create the virtual environment
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

COPY microservices/Shared/ /build/Shared/
COPY microservices/Torri/ /build/Torri/
COPY microservices/Executor/ /build/Executor/

# Install the packages into the virtualenv using uv
RUN uv pip install --no-cache ./Shared && \
    uv pip install --no-cache ./Torri && \
    uv pip install --no-cache ./Executor

# ==========================================
# Stage 2: Runtime Base Layer
# ==========================================
FROM python:3.12-slim AS runtime-base

# Install supervisor, git, openssh-server and openssh-client in the base layer
RUN apt-get update && \
    apt-get install -y git openssh-client openssh-server supervisor && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/run/sshd /var/log/supervisor

# Retrieve the virtual environment and uv binary
COPY --link --from=builder /opt/venv /opt/venv
COPY --link --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY --link microservices/Shared/ /app/Shared/
COPY --link microservices/Torri/ /app/Torri/
COPY --link microservices/Executor/ /app/Executor/

# Copy shared logging configuration to a central location
COPY --link microservices/Torri/src/torri/config/log/ /app/config/log/

ENV PYTHONPATH="/app/Shared/src:/app/Torri/src:/app/Executor/src"

# Set Supervisor as the primary entrypoint for the base runtime
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]

# ==========================================
# Stage 3: Merger Service (Target: merger)
# ==========================================
FROM runtime-base AS merger

# Copy the custom supervisord configuration for the Merger
COPY --link compose/files/ssh/ /home/git/.ssh/
COPY --link compose/files/supervisor/merger/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN useradd -o -u 0 -g 0 -m -d /home/git -s /usr/bin/git-shell git && \
    mkdir -p /home/git/.ssh /tmp/torri_workspaces
# Symlink for SSH config compatibility: /root/.ssh -> /home/git/.ssh
RUN chmod 700 /home/git/.ssh && chmod 600 /home/git/.ssh/Torri_ed25519
RUN rm -rf /root/.ssh && ln -s /home/git/.ssh /root/.ssh

# Configure Git user for merge commit creation
RUN git config --global user.email "torii@localdomain" && \
    git config --global user.name "Torii Merger"

EXPOSE 22

# ==========================================
# Stage 4: Scheduler Service (Target: scheduler)
# ==========================================
FROM runtime-base AS scheduler

# Copy the custom supervisord configuration for the Scheduler
COPY compose/files/supervisor/scheduler/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY compose/files/supervisor/scheduler/status_api.conf /etc/supervisor/conf.d/status_api.conf

# Bake the pipeline/project/job YAML files into the image.
# These override whatever ships inside microservices/Torri so compose/files/torri/
# stays the single source of truth for deployed configuration.
COPY compose/files/torri/ /app/Torri/src/torri/config/layout/

RUN mkdir -p /app/logs

# ==========================================
# Stage 5: Executor Service (Target: executor)
# ==========================================
FROM runtime-base AS executor

# Install Docker CLI so the executor can spin up containers via the host socket.
RUN apt-get update && \
    apt-get install -y docker.io && \
    rm -rf /var/lib/apt/lists/*

# Copy the custom supervisord configuration for the Executor
COPY --link compose/files/supervisor/executor/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy executor configuration
COPY --link microservices/Executor/src/executor/executor.conf /app/Executor/src/executor/executor.conf

# Copy SSH key for merger authentication
COPY --link compose/files/ssh/Torri_ed25519 /root/.ssh/Torri_ed25519
COPY --link compose/files/ssh/config /root/.ssh/config

RUN chmod 700 /root/.ssh && chmod 600 /root/.ssh/Torri_ed25519

# Create executor working directories
RUN mkdir -p /var/torii/jobs /etc/torri /app/logs


