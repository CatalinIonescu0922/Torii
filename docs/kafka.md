# Kafka in Torii

## What Kafka Is

Kafka is a distributed event streaming platform. At its core it is a durable, ordered, replayable log. Producers write messages to named topics; consumers read from those topics at their own pace. Kafka holds messages for a configurable retention period regardless of whether they have been consumed, which means a consumer can restart and catch up from exactly where it left off.

---

## Where Torii Uses Kafka

Torii uses Kafka as the backbone for every inter-service message. Nothing talks to another service over a direct HTTP call for fire-and-forget work — it writes to a topic instead.

| Topic | Producer | Consumer | Purpose |
|-------|----------|----------|---------|
| `gerrit-stream-events` | Gerrit Kafka plugin | `KafkaConnection` (scheduler) | Raw Gerrit events (patchset-created, comment-added, change-merged, …) |
| `trigger-events` | `GerritEventProcessor` | `TriggerBridge` (scheduler) | Enriched, validated trigger events after REST annotation |
| `merger-requests` | `SchedulerQueue` | Merger service | Requests to speculatively merge a change |
| `merger-responses` | Merger service | `SchedulerQueue` | Merge outcome (success / failure + ref) |

The flow looks like this:

```
Gerrit ──► gerrit-stream-events ──► KafkaConnection
                                          │
                                    GerritEventProcessor
                                    (enriches via Gerrit REST)
                                          │
                                    trigger-events ──► TriggerBridge
                                                              │
                                                       SchedulerQueue
                                                              │
                                                    merger-requests ──► Merger
                                                              │
                                                    merger-responses ◄── Merger
```

---

## Why Kafka and Not RabbitMQ

Both are solid choices. The decision comes down to the properties that matter most for a CI/CD scheduler.

### Replay and catch-up

Kafka retains messages on disk for a configurable window (hours, days). If the scheduler restarts mid-event storm it replays from its last committed offset and misses nothing. RabbitMQ is a queue: once a message is acknowledged and removed it is gone. A crashed consumer loses anything that was in-flight or delivered but not ACK'd before the crash.

### Ordering guarantees

Kafka guarantees ordering within a partition. Gerrit events for the same change (patchset-created → comment-added → change-merged) can be keyed by change number, keeping them in the same partition and therefore strictly ordered. RabbitMQ can reorder messages under certain routing or HA configurations.

### Back-pressure and consumer independence

Kafka decouples producer speed from consumer speed. The Gerrit plugin can burst a large number of events during a busy review period; the scheduler consumes them at its own rate without the broker being overwhelmed. RabbitMQ pushes messages to consumers (push model by default), which can overwhelm a slow consumer unless prefetch tuning is done carefully.

### Operational simplicity for this use case

Torii already runs Kafka (required by the Gerrit plugin that publishes stream events). Adding RabbitMQ would introduce a second broker technology with its own ops surface for no gain. Keeping everything on Kafka means one tool to operate, monitor, and reason about.

### What RabbitMQ would be better at

RabbitMQ has richer routing primitives (exchanges, bindings, topic patterns) and lower latency for simple point-to-point queues. For a system that only needs a handful of well-known topics and values replay/durability over microsecond latency, those advantages do not outweigh Kafka's benefits.

---

## Manual Commit Strategy

`KafkaConnection` uses manual offset commits (`enable.auto.commit = false`). An event is committed only after it has been placed on the internal `event_queue`, ensuring that a crash between poll and enqueue causes the message to be re-delivered on restart rather than silently dropped. Bad messages (unparseable JSON, empty payloads) are committed immediately to skip them without blocking the queue.

---

## Configuration

All Kafka coordinates live in `torii.conf` — never in environment variables for runtime settings.

```ini
[connection kafka]
bootstrap_servers=kafka:9092

[connection gerrit]
kafka_bootstrap_servers=kafka:9092
kafka_group_id=gerrit-events
kafka_topic=gerrit-events

[merger]
kafka_bootstrap_servers=kafka:9092
kafka_group_id=merger
kafka_topic_requests=merger-requests
kafka_topic_responses=merger-responses
```

The group IDs matter: each service uses a distinct group so that every service receives every message on shared topics independently.
