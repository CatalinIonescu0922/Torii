# Intelligence Layer: Event-Driven Ingestor
## Architecture & Flow Documentation

---

## Overview

This microservice acts as a **High-Speed Translator** between Gerrit events and your CI Scheduler. It operates as a stateless, event-driven ingestor that filters, validates, and routes data in real-time without storing long-term state.

---

## 1. Three-Layer Architecture

### Layer A: Transport Layer (Kafka Consumer)
**Responsibility:** Manages the connection to Kafka and raw data ingestion

**Flow:**
1. **Connection Establishment**
   - Connect to Kafka cluster using bootstrap servers
   - Subscribe to `gerrit-events` topic
   - Configure consumer group for load distribution

2. **Polling Loop**
   - Continuously poll Kafka for new messages
   - Set appropriate timeout values (e.g., 1 second per poll)
   - Handle empty poll responses gracefully

3. **Deserialization**
   - Receive raw bytes from Kafka
   - Decode to UTF-8 string
   - Parse string to JSON object

4. **Fault Tolerance**
   - Implement retry logic for transient Kafka failures
   - Handle connection drops with exponential backoff
   - Log connection issues for monitoring

5. **Manual Commit Strategy**
   - DO NOT auto-commit offsets
   - Only commit after successful processing and publishing
   - Ensures at-least-once delivery semantics

---

### Layer B: Validation Layer (Pydantic Models)
**Responsibility:** Ensure data integrity before processing

**Flow:**
1. **Raw JSON Input**
   - Receive parsed JSON from Transport Layer
   - JSON contains full Gerrit event (potentially 150+ lines)

2. **Model Matching**
   - Identify event type from JSON (e.g., `type: "patchset-created"`)
   - Route to appropriate Pydantic model:
     - `PatchSetCreatedEvent`
     - `CommentAddedEvent`
     - `ChangeMergedEvent`
     - (other Gerrit event types)

3. **Validation Process**
   - Pydantic automatically checks:
     - Required fields exist (`project`, `patchSet`, `change`)
     - Data types are correct (strings, integers, nested objects)
     - Enums match expected values
   - If validation fails:
     - Log the error with full context
     - Mark message as processed (commit offset)
     - Continue to next message (don't crash the service)

4. **Type Safety Output**
   - Output: Strongly-typed Python object
   - All subsequent code can safely access fields without try/except
   - Example: `event.patchSet.revision` is guaranteed to be a string

---

### Layer C: Logic Layer (Router & Handlers)
**Responsibility:** Business logic and decision-making

#### C.1: Event Router

**Flow:**
1. **Receive Validated Event**
   - Input: Pydantic model instance from Layer B

2. **Event Type Mapping**
   ```
   Event Type              → Handler Function
   ────────────────────────────────────────────
   "patchset-created"      → PatchSetCreatedHandler
   "comment-added"         → CommentAddedHandler
   "change-merged"         → ChangeMergedHandler
   "draft-published"       → DraftPublishedHandler
   (others)                → GenericHandler (log & ignore)
   ```

3. **Handler Invocation**
   - Call appropriate handler function
   - Pass the validated event object
   - Receive routing decision from handler

4. **Routing Decision Types**
   - `TRIGGER_BUILD`: Create internal job and publish
   - `IGNORE`: Log and skip (no action needed)
   - `ERROR`: Log error details and commit offset

---

#### C.2: Handler Details

##### **PatchSetCreatedHandler**

**Purpose:** Trigger initial builds when new patchsets are uploaded

**Decision Flow:**
1. Extract core data:
   - Project name: `event.change.project`
   - Commit revision: `event.patchSet.revision`
   - Ref (branch): `event.patchSet.ref`
   - Author: `event.patchSet.uploader.email`

2. Apply filters:
   - Is this a WIP (Work In Progress) change? → IGNORE
   - Is the project in the monitored list? → If NO: IGNORE
   - Is this a private change? → IGNORE

3. If all filters pass:
   - Decision: **TRIGGER_BUILD**
   - Construct `InternalJob`:
     - `project`: The project name
     - `commit_hash`: The revision
     - `ref`: The branch reference
     - `trigger_type`: "patchset-created"
     - `metadata`: Additional context (author, patchset number)

4. Publish to `ci-internal-triggers` topic

---

##### **CommentAddedHandler**

**Purpose:** Trigger builds based on manual review labels

**Decision Flow:**
1. Extract comment data:
   - Project name: `event.change.project`
   - Commit revision: `event.patchSet.revision`
   - Ref: `event.patchSet.ref`
   - Author: `event.author.email`
   - Approvals: `event.approvals[]` (list of labels)

2. Label Analysis (iterate through approvals):
   ```
   Label          Old Value    New Value    Action
   ───────────────────────────────────────────────────
   Verified       0            +1           TRIGGER_BUILD
   Verified       0            -1           IGNORE
   Verified       +1           -1           (Optional: CANCEL_BUILD)
   Code-Review    0            +2           TRIGGER_BUILD (if enabled)
   Code-Review    0            +1           IGNORE (not enough)
   Code-Review    +1           +2           TRIGGER_BUILD
   ```

3. **Decision Logic Options:**

   **Option A: Simple Positive Signal**
   - If ANY approval goes from non-positive to positive (+1, +2)
   - Decision: **TRIGGER_BUILD**

   **Option B: Specific Label Requirements**
   - Define required labels per project (e.g., `Verified+1` required)
   - Only trigger if specific label threshold is met
   - Example: Only `Verified+1` triggers, ignore `Code-Review`

   **Option C: Combined Labels**
   - Require BOTH `Code-Review+2` AND `Verified+1`
   - Only trigger when both thresholds are met

4. If trigger condition met:
   - Construct `InternalJob`:
     - `project`: The project name
     - `commit_hash`: The revision
     - `ref`: The branch reference
     - `trigger_type`: "comment-added"
     - `metadata`: 
       - `triggered_by`: Author email
       - `label`: Which label triggered it
       - `value`: The new label value

5. Publish to `ci-internal-triggers` topic

---

##### **ChangeMergedHandler**

**Purpose:** Trigger post-merge jobs (deployment, tagging, etc.)

**Decision Flow:**
1. Extract merge data:
   - Project name: `event.change.project`
   - Commit revision: `event.patchSet.revision`
   - Target branch: `event.change.branch`
   - Merged by: `event.submitter.email`

2. Apply filters:
   - Is this a protected branch (master, main, release/*)? 
     - YES → TRIGGER_BUILD
     - NO → Check project configuration

3. Construct `InternalJob`:
   - `trigger_type`: "change-merged"
   - `metadata`:
     - `merged_by`: Submitter email
     - `branch`: Target branch
     - (useful for deployment pipelines)

---

## 2. Complete Data Flow Example

### Example: "comment-added" event with Verified+1

```
┌─────────────────────────────────────────────────────────────┐
│ 1. GERRIT PUSHES EVENT TO KAFKA                             │
│    Topic: gerrit-events                                      │
│    Payload: 150-line JSON with full change context          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. TRANSPORT LAYER (Kafka Consumer)                         │
│    - Poll Kafka (1 second timeout)                          │
│    - Receive message bytes                                   │
│    - Deserialize to JSON string                             │
│    - Parse to Python dict                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. VALIDATION LAYER (Pydantic)                              │
│    - Detect type: "comment-added"                           │
│    - Instantiate CommentAddedEvent model                    │
│    - Validate required fields:                              │
│      ✓ event.change.project: "my-repo"                      │
│      ✓ event.patchSet.revision: "abc123..."                 │
│      ✓ event.approvals[0].type: "Verified"                  │
│      ✓ event.approvals[0].value: "1"                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. LOGIC LAYER - ROUTER                                     │
│    - Check event.type → "comment-added"                     │
│    - Route to: CommentAddedHandler                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. LOGIC LAYER - CommentAddedHandler                        │
│    - Extract approvals list                                 │
│    - Find: Verified changed from 0 → +1                     │
│    - Decision: TRIGGER_BUILD                                │
│    - Create InternalJob:                                    │
│      {                                                       │
│        "project": "my-repo",                                │
│        "commit_hash": "abc123...",                          │
│        "ref": "refs/changes/42/12345/3",                    │
│        "trigger_type": "comment-added",                     │
│        "metadata": {                                        │
│          "triggered_by": "reviewer@company.com",            │
│          "label": "Verified",                               │
│          "value": "+1"                                      │
│        }                                                     │
│      }                                                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. PUBLISH TO KAFKA                                         │
│    Topic: ci-internal-triggers                              │
│    Payload: Slim 10-line JSON (InternalJob)                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. COMMIT KAFKA OFFSET                                      │
│    - Tell Kafka: "I'm done with this message"               │
│    - If container crashes before this: message replays      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. CI SCHEDULER CONSUMES                                    │
│    - Reads from ci-internal-triggers                        │
│    - Schedules actual build job                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Key Reliability Features

### At-Least-Once Delivery

**Guarantee:** Every Gerrit event will be processed at least once

**Implementation:**
1. Disable Kafka auto-commit
2. Only commit offset after:
   - Validation succeeds
   - Handler completes
   - Internal job is published
   - No exceptions occurred

3. If crash occurs:
   - Kafka retains the uncommitted message
   - On restart, message is redelivered
   - Idempotent downstream handling required

---

### Stateless Scaling

**Benefit:** Horizontal scaling without coordination

**How it works:**
1. Each container instance:
   - Joins the same Kafka consumer group
   - Receives a partition assignment from Kafka
   - Processes messages independently

2. Scaling scenarios:
   - 1 instance: Processes all partitions sequentially
   - 3 instances: Kafka assigns ~33% of partitions to each
   - 10 instances: Each handles ~10% of the load

3. No shared state:
   - No database needed
   - No Redis cache
   - No inter-process communication
   - Pure message transformation

---

### Backpressure Handling

**Problem:** What if downstream CI workers are full?

**Solution:**
- This service doesn't care!
- It keeps publishing to `ci-internal-triggers`
- Kafka acts as the buffer (can hold millions of messages)
- CI Scheduler consumes at its own pace
- Natural flow control via Kafka retention

---

## 4. Error Handling Strategy

### Error Categories

| Error Type | Action | Reason |
|------------|--------|--------|
| Kafka connection failure | Retry with backoff | Transient network issue |
| Validation failure | Log + Commit offset | Bad data from Gerrit (skip it) |
| Unknown event type | Log + Commit offset | New Gerrit event type (ignore for now) |
| Handler exception | Log + Commit offset | Bug in handler logic (don't block queue) |
| Publish failure | Retry 3x, then log + commit | Kafka issue, but don't block indefinitely |

### Logging Requirements

**Essential logs:**
1. **INFO:** Each event processed (type, project, commit)
2. **WARNING:** Validation failures, unknown event types
3. **ERROR:** Handler exceptions, publish failures
4. **DEBUG:** Full event JSON (only in development)

---

## 5. Configuration Requirements

### Kafka Configuration
```
# Consumer settings
bootstrap.servers: kafka-broker-1:9092,kafka-broker-2:9092
group.id: events-consumer-group
enable.auto.commit: false
auto.offset.reset: earliest  (start from beginning on first run)
max.poll.interval.ms: 300000  (5 minutes - plenty of time)

# Producer settings (for publishing internal jobs)
acks: all  (wait for all replicas)
retries: 3
```

### Application Configuration
```
# Topics
KAFKA_INPUT_TOPIC: gerrit-events
KAFKA_OUTPUT_TOPIC: ci-internal-triggers

# Filtering
MONITORED_PROJECTS: [list of project names to watch]
IGNORED_AUTHORS: [bot accounts to ignore]

# Handler Configuration
TRIGGER_ON_VERIFIED_PLUS_ONE: true
TRIGGER_ON_CODE_REVIEW_PLUS_TWO: false
REQUIRE_BOTH_LABELS: false
```

---

## 6. Testing Strategy

### Unit Tests
- Each handler function with mock events
- Validation layer with malformed JSON
- Router with all event types

### Integration Tests
- Full flow with test Kafka instance
- Publish test Gerrit events
- Verify internal jobs are created correctly

### Load Tests
- 1,000 events/second throughput test
- Measure lag (time from Gerrit event to internal job)
- Target: < 100ms average latency

---

## 7. Implementation Checklist

### Phase 1: Foundation
- [ ] Set up Kafka consumer client
- [ ] Implement polling loop
- [ ] Add basic error handling
- [ ] Test connection to Kafka cluster

### Phase 2: Validation
- [ ] Create Pydantic models in `shared/model.py`
- [ ] Implement event type detection
- [ ] Add validation error logging
- [ ] Test with real Gerrit event samples

### Phase 3: Handlers
- [ ] Implement Router logic
- [ ] Build PatchSetCreatedHandler
- [ ] Build CommentAddedHandler
- [ ] Build ChangeMergedHandler
- [ ] Test each handler independently

### Phase 4: Publishing
- [ ] Set up Kafka producer
- [ ] Implement InternalJob publishing
- [ ] Add manual commit logic
- [ ] Test end-to-end flow

### Phase 5: Production Readiness
- [ ] Add comprehensive logging
- [ ] Implement metrics (events/sec, lag, errors)
- [ ] Create health check endpoint
- [ ] Add graceful shutdown handling
- [ ] Write Dockerfile
- [ ] Document deployment procedure

---

## 8. Decision Logic Configuration

### Recommended Approach: Configuration Matrix

For maximum flexibility, use a configuration file that maps:
```
Project → Event Type → Label Requirements → Action
```

**Example Decision Matrix:**

| Project | Event Type | Label | Threshold | Action |
|---------|------------|-------|-----------|--------|
| core-api | patchset-created | - | - | TRIGGER_BUILD |
| core-api | comment-added | Verified | +1 | TRIGGER_BUILD |
| core-api | comment-added | Code-Review | +2 | TRIGGER_BUILD |
| core-api | change-merged | - | - | TRIGGER_BUILD (deploy) |
| docs-site | patchset-created | - | - | TRIGGER_BUILD |
| docs-site | comment-added | Verified | +1 | IGNORE (no CI for docs) |
| legacy-app | patchset-created | - | - | IGNORE (deprecated) |

This matrix allows you to:
- Enable/disable CI per project
- Require different labels for different projects
- Add new projects without code changes
- A/B test different triggering strategies

---

## 9. Monitoring & Observability

### Key Metrics to Track
1. **Throughput:** Events processed per second
2. **Lag:** Time between Gerrit event and internal job creation
3. **Error Rate:** % of messages that fail validation or handling
4. **Commit Rate:** Successful offset commits per minute

### Health Check Endpoint
- Expose `/health` HTTP endpoint
- Check: Can connect to Kafka?
- Check: Is consumer loop running?
- Return 200 OK or 503 Service Unavailable

---

## 10. Future Enhancements

1. **Dynamic Handler Loading:** Load handlers from plugins without restart
2. **Event Replay:** Admin endpoint to replay specific events
3. **Rate Limiting:** Prevent Gerrit from overwhelming the system
4. **Multi-Topic Output:** Route different job types to different topics
5. **Dead Letter Queue:** Send failed messages to separate topic for analysis

---

## Next Steps

1. Review this flow with your team
2. Define the exact label requirements for your CommentAddedHandler
3. Gather sample Gerrit event JSON files for testing
4. Set up your Kafka development cluster
5. Begin Phase 1 implementation

**Questions to Answer Before Implementation:**
- Which Gerrit labels should trigger builds? (Verified, Code-Review, Custom-CI?)
- Should WIP changes be ignored or processed?
- Do you want to support custom labels per project?
- What's your target latency (time from Gerrit event to CI job start)?
- Do you need to support event replay for debugging?
