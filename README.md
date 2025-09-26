# Torii — Lightweight CI Platform

Torii is an all‑in‑one continuous integration platform that helps you test
and merge code changes with confidence. It integrates with Gerrit for code
review, pre‑merges changes in an isolated staging area so jobs see the
"merged state," dispatches builds to a worker pool, and reports results back
to Gerrit.

This project is built by Catalin Ionescu as a final exam project.

## Overview

Torii focuses on three pillars:

- Correctness: test the code as it would look after a merge (pre‑merge).
- Speed: schedule work efficiently and run jobs on scalable workers.
- Feedback: report clear results back to the code review system.

## Core Components

- Gerrit: Git server and code review system. Source of events (e.g.,
  `patchset-created`, `change-merged`).
- Torii Scheduler: Listens to Gerrit events, deduplicates and prioritizes
  work, determines which pipelines to run, and enqueues tasks.
- Merger Service: Preemptively merges or rebases the change into a staging
  branch to expose the full, merged code to jobs. Handles conflicts and
  updates status appropriately.
- Job Dispatcher: Abstraction layer that launches jobs on available workers.
  Initial target is Gearman,the interface may implement something diffrent 
- Execution Layer: A Jenkins agent and one or more workers to provide a
  consistent runtime environment for jobs.
- (Optional) Artifacts + Logs: Storage for build outputs and logs (e.g.,
  S3/MinIO) with links back to the review.

## High‑Level Flow

1. A developer pushes a change; Gerrit creates/updates a patchset.
2. Gerrit emits an event; the Torii Scheduler receives it.
3. The Scheduler determines the required pipeline(s) for the project.
4. The Merger Service pre‑merges or rebases into a temporary integration
   branch (isolated workspace) and exposes that to jobs.
5. The Job Dispatcher assigns work to available workers (via Gearman or
   another backend) and tracks execution.
6. Workers run the pipeline steps (build, test, lint, etc.), producing logs
   and artifacts.
7. Results are collected and published; Torii reports status/comments back to
   Gerrit (e.g., votes, messages, links to logs/artifacts).
8. On `change-merged`, Torii can trigger post‑merge pipelines as needed.

## Design Notes & Improvements

- Pre‑merge testing: Ensures jobs see the final merged state, catching issues
  caused by mainline drift early.
- Isolation & reproducibility: Use ephemeral workspaces and containerized
  environments for deterministic builds.
- Caching & artifacts: Optional shared caches and artifact storage to speed
  up builds and support debugging.
- Secrets management: Integrate with a secret store (e.g., Vault or
  Kubernetes secrets) for credentials.
- Scalability: Backpressure and prioritization in the Scheduler; horizontal
  scaling of workers.
- Pipeline‑as‑code (proposed): A simple `torii.yml` in each repo to declare
  jobs, triggers, and required environments.
- Observability: Metrics and structured logs for the Scheduler, Merger, and
  Dispatcher.

## Project Status

Early stage. Architecture and interfaces are being defined, followed by
incremental implementation of the Scheduler, Merger, and Dispatcher.

## Roadmap

- [ ] Define `torii.yml` pipeline spec
- [ ] Implement Gerrit event listener (stream‑events or webhooks)
- [ ] MVP Scheduler with queueing and deduplication
- [ ] Merger Service (fast‑forward, rebase, conflict handling)
- [ ] Job Dispatcher with Gearman backend
- [ ] Jenkins agent integration + worker pool
- [ ] Result reporting back to Gerrit (votes, comments, links)
- [ ] Optional artifact/log storage
- [ ] Observability (metrics, tracing)

## Getting Started (WIP)

Prerequisites (depending on deployment choice):

- A Gerrit instance you can access.
- A worker environment (Jenkins agent + workers, or containers).
- A job backend (Gearman to start; alternatives possible).

Local development will include Docker Compose setups for the Merger,
Scheduler, and a minimal Dispatcher, plus example pipelines.

## Contributing

Issues and PRs are welcome as the project takes shape. For major changes,
please open an issue first to discuss what you would like to change.

## Author

Created by Catalin Ionescu.

## License

TBD.
