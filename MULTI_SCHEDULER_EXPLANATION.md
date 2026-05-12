# Torri: Single-Threaded Per Instance vs Multiple Instances

## Your Question

> I am gonna have multiple schedulers? If I have multiple schedulers, things are gonna be hard when merging changes or pushing updates to the UI?

## Answer: NO, It's Actually EASIER with Multiple Schedulers!

---

## Key Concept: Single-Threaded PER INSTANCE

```
❌ WRONG INTERPRETATION:
   Entire Torri system is single-threaded
   → Can only handle one thing at a time
   → Multiple schedulers conflict

✓ CORRECT INTERPRETATION:
   Each scheduler INSTANCE is single-threaded
   → Each processes events sequentially (consistent)
   → Multiple instances run in parallel (scalable)
   → Redis locks prevent conflicts (safe)
```

---

## How It Works: The Lock-Based Model

```
                THREE SCHEDULERS
              (All running simultaneously)

         Scheduler-1 (SingleThread)
              Event Loop:
              While True:
                  1. Acquire lock
                  2. Process pipeline
                  3. Release lock
              
         Scheduler-2 (SingleThread)
              Event Loop:
              While True:
                  1. Try to acquire lock ← BLOCKED
                  2. Wait...
                  3. Once lock free, acquire
                  4. Process pipeline
         
         Scheduler-3 (SingleThread)
              Event Loop:
              While True:
                  1. Try to acquire lock ← BLOCKED
                  2. Wait...
                  3. Once lock free, acquire
                  4. Process pipeline


                    REDIS
              (Central Coordination)
         
         Locks:
         ├─ "lock:pipeline:check"
         ├─ "lock:pipeline:gate"
         ├─ "lock:global:merge"
         
         When Scheduler-1 has lock:
         └─ S2 and S3 wait
              └─ When released, next scheduler takes it
                   └─ Process guaranteed serial & consistent
```

---

## Merge Safety: Global Merge Lock

```
Multiple Schedulers TRY TO MERGE SIMULTANEOUSLY

Scenario: Change A ready to merge

    Scheduler-1          Scheduler-2          Scheduler-3
        │                   │                    │
        ├─ Try MERGE_LOCK → SUCCESS ✓
        │                    │                   │
        ├─ GIT MERGE        ├─ Waiting...      ├─ Waiting...
        │ [atomic op]       │ [spinning]       │ [spinning]
        │                   │                   │
        └─ Git proceeds     │                   │
          ONLY HERE         │                   │
                           │                   │
               [Change A is now merged]         │
                            │                   │
                ├─ Release MERGE_LOCK ✓
                │                   │
                ├─ Scheduler-2 acquires lock
                │
                └─ Scheduler-2 proceeds
                   with Change B
                   
RESULT: 
✓ No race conditions
✓ No merge conflicts
✓ No data corruption
✓ All updates reach UI
```

---

## UI Updates: Broadcast Pattern

```
MULTIPLE SCHEDULER INSTANCES

    S1: Processes → Change A merged
        │
        ├─ Updates Redis change:A:state = MERGED
        │
        ├─ Publishes to Redis Pub/Sub: "ui:events"
        │
        └─ ALL WEB CLIENTS receive notification
           ├─ Client 1: ✓ Instant update
           ├─ Client 2: ✓ Instant update
           └─ Client 3: ✓ Instant update


NO MATTER WHICH SCHEDULER PROCESSES IT

    S2: Processes → Change B failed
        │
        ├─ Updates Redis change:B:state = FAILURE
        │
        ├─ Publishes to Redis Pub/Sub: "ui:events"
        │
        └─ ALL WEB CLIENTS receive notification (same instant!)


REDIS PUB/SUB GUARANTEES:

┌─ All messages published
├─ All subscribers notified
├─ Ordering preserved (per channel)
└─ No duplicates, no loss
```

---

## Timeline: The Exact Flow

```
T0: Gerrit: "Patchset created" → Kafka topic: gerrit-events

T1: ALL 3 Schedulers see event on Kafka
    ├─ Scheduler-1 pops event first
    ├─ Scheduler-2 doesn't pop (S1 already did)
    └─ Scheduler-3 doesn't pop

    (Kafka ensures each message consumed once)

T2: Scheduler-1 processes change
    ├─ Enqueues to pipeline:check
    ├─ Marks pipeline dirty
    └─ Redis: change:state is updated

T3: Scheduler-1 runs pipeline
    ├─ Acquires "lock:pipeline:check"
    ├─ Dequeues change
    ├─ Creates jobs
    └─ Schedules to executor (via Kafka)

T4: Executor runs jobs, publishes results to Kafka

T5: ALL 3 Schedulers receive job result
    ├─ S1: Has lock, updates local state
    ├─ S2: Doesn't have lock, marks pipeline dirty
    └─ S3: Doesn't have lock, marks pipeline dirty

T6: Scheduler-1 releases pipeline lock

T7: Schedulers 2 & 3 compete for lock
    ├─ Winner: Scheduler-2!
    ├─ Scheduler-2 processes next change
    └─ Scheduler-3 waits

T8: All changes in pipeline go through this loop
    ├─ Some processed by S1
    ├─ Some processed by S2
    ├─ Some processed by S3
    └─ BUT always serial per pipeline, parallel across pipelines


EVENT BROADCAST (always to all clients):

    Any Scheduler: Change merged!
        │
        ├─ Redis: Pub/Sub publish
        │
        └─ UI CLIENTS:
            ├─ Browser 1: notification ✓
            ├─ Browser 2: notification ✓
            ├─ Browser 3: notification ✓
            └─ All at same time!
```

---

## Why This Design is BETTER

| Concern | Single Instance | Multiple Instances |
|---------|-----------------|-------------------|
| **Scale** | Limited by single process | Horizontal scaling ✓ |
| **Availability** | Single point of failure | HA/redundancy ✓ |
| **Throughput** | Pipelines sequential | Pipelines parallel ✓ |
| **Merge conflicts** | Can happen (but rare) | Prevented by locks ✓ |
| **UI consistency** | Can get stale | Real-time via Pub/Sub ✓ |
| **Complexity** | Simple but risky | Robust but elegant ✓ |

---

## Deployment Scenarios

### Development (1 Scheduler)
```
docker-compose up scheduler
  └─ Single instance
  └─ Full functionality
  └─ Same behavior as multi-instance
```

### Staging (3 Schedulers)
```
docker-compose up scheduler-1 scheduler-2 scheduler-3
  ├─ Normal load balancing
  ├─ Some HA
  ├─ Test multi-scheduler interactions
  └─ But simpler than production
```

### Production (10 Schedulers + Load Balancer)
```
kubernetes:
  ├─ StatefulSet: 10 scheduler replicas
  ├─ Service: Load balancer over replicas
  ├─ Redis: Managed (e.g., AWS ElastiCache)
  ├─ Kafka: Managed (e.g., AWS MSK)
  └─ Maximum availability & throughput
```

---

## The Bottom Line

```
┌─────────────────────────────────────────┐
│ SINGLE-THREADED PER INSTANCE            │
│ ≠ Single-threaded system                │
│                                         │
│ It's:                                   │
│ • Each scheduler is single-threaded     │
│ • Ensures consistency within scheduler  │
│ • Prevents race conditions              │
│                                         │
│ • Multiple schedulers run in parallel   │
│ • Locks prevent conflicts between them  │
│ • Redis Pub/Sub broadcasts to all       │
│ • UI clients get real-time updates      │
│                                         │
│ RESULT: Scalable, consistent, fast!    │
└─────────────────────────────────────────┘
```

---

## Technical Implementation

No changes needed! The architecture already handles this:

```python
# Each scheduler instance:

async def main_event_loop():
    while True:
        # Single-threaded, atomic operations
        lock = await acquire_lock("pipeline:check")
        try:
            process_pipeline()
        finally:
            release_lock(lock)

# Multiple instances run this simultaneously
# Locks ensure no conflicts
# Redis Pub/Sub propagates updates to UI

# Result: Perfect coordination!
```

---

## Questions?

- **Q: What if two schedulers try to merge same change?**
  - A: Global MERGE_LOCK prevents it. Only one succeeds.

- **Q: What about race conditions in Redis?**
  - A: Redis is atomic. All reads/writes atomic. No races.

- **Q: What if network splits between schedulers?**
  - A: Locks have timeouts. Stale nodes auto-release. Recovery built-in.

- **Q: UI gets stale data?**
  - A: Redis Pub/Sub broadcasts. Real-time. No caching issues.

- **Q: Can I start with 1 and grow to 10?**
  - A: Yes! Same code, just scale horizontally. Perfect.
