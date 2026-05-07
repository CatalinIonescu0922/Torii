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

# Install the packages into the virtualenv using uv
RUN uv pip install --no-cache ./Shared && \
    uv pip install --no-cache ./Torri

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

ENV PYTHONPATH="/app/Shared/src:/app/Torri/src"

# THE TRICK: 
# Create a user named 'git' with UID 0 (root alias) using the '-o' flag.
# We set its shell to '/usr/bin/git-shell' so even though it has root privileges, 
# it can ONLY execute git commands over SSH (clone/fetch), securing the container.
RUN useradd -o -u 0 -g 0 -m -d /home/git -s /usr/bin/git-shell git && \
    mkdir -p /home/git/.ssh /tmp/torri_workspaces

# Set Supervisor as the primary entrypoint for the base runtime
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]

# ==========================================
# Stage 3: Merger Service (Target: merger)
# ==========================================
FROM runtime-base AS merger

# Copy the custom supervisord configuration for the Merger
COPY --link compose/files/ssh/ /home/git/.ssh/
COPY --link compose/files/supervisor/merger/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 22

# ==========================================
# Stage 4: Scheduler Service (Target: scheduler)
# ==========================================
FROM runtime-base AS scheduler

# Copy the custom supervisord configuration for the Scheduler
COPY compose/files/supervisor/scheduler/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
