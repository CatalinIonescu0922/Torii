# Gate Pipeline Algorithm Implementation

**Status:** ✅ IMPLEMENTED
**Date:** May 12, 2026
**Scope:** Complete ordered, dependent execution with speculative testing

---

## Architecture Overview

The Gate pipeline algorithm is implemented across 4 core modules:

```
┌─────────────────────────────────────────────────────────────────┐
│ GatePipeline (pipeline_manager.py)                              │
│ - High-level pipeline interface                                  │
│ - Delegates to GateAlgorithm                                     │
└────────────────┬────────────────────────────────────────────────┘
                 │
    ┌────────────┴────────────┬──────────────────┬─────────────┐
    ↓                         ↓                  ↓             ↓
GateAlgorithm          DependencyManager  MergeCoordinator  SpeculativeMerger
(gate_algorithm.py)    (dependency_..py)  (merge_coord..py) (speculative..py)
- Orchestration        - Tracking deps    - Merge logic     - Merge bases
- State changes        - Cascading        - Validation      - Rebasing
- Queue processing     - Reordering       - Locking         - Conflict detect
```

---

## Module Responsibilities

### 1. **GatePipeline** (`pipeline_manager.py`)

High-level interface for Gate pipeline operations.

**Key Methods:**
```python
enqueue_change(change_id, project_name, branch)
  → Enqueues using GateAlgorithm if available

start_speculative_testing(change_id)
  → Begins speculative execution on merge base

mark_test_success(change_id)
  → Tests passed, ready for merge validation

mark_test_failure(change_id, reason)
  → Tests failed, cascade to dependents

attempt_merge(change_id, gerrit_change)
  → Execute merge with validation and locks

handle_merge_conflict(change_id, old_base, new_base)
  → Rebase and restart tests on new base
```

**Data Flow:**
```
Event arrives → enqueue_change()
  ↓
start_speculative_testing()
  ↓
Tests run on merge base
  ↓
Test completes:
  ├─ Success → mark_test_success() → attempt_merge()
  └─ Failure → mark_test_failure() → cascade to dependents
```

---

### 2. **GateAlgorithm** (`gate_algorithm.py`)

Core orchestration logic for the 5-phase pipeline.

**Phases:**

**Phase 1: Queuing**
```python
enqueue_change() → dependencies.register_change()
                → speculative_merger.calculate_merge_base()
                → redis.queue_enqueue()
```

**Phase 2: Speculative Execution**
```python
start_speculative_testing() → speculative_merger.can_merge_speculatively()
                            → redis.update_state('TESTING')
```

**Phase 3: Test Results**
```python
handle_test_success()   → redis.update_state('MERGE_READY')
handle_test_failure()   → redis.update_state('FAILED')
                       → dependencies.notify_dependents_of_failure()
```

**Phase 4: Merge**
```python
attempt_merge() → merge_coordinator.validate_before_merge()
               → merge_coordinator.acquire_merge_lock()
               → _execute_merge() (Gerrit API call)
               → merge_coordinator.release_merge_lock()
```

**Phase 5: Queue Processing**
```python
process_queue() → Gets window size
               → Calculates available slots
               → Dequeues changes
               → Starts testing for each
               → Updates window tracking
```

---

### 3. **DependencyManager** (`dependency_manager.py`)

Tracks change dependencies and cascade failures.

**Key Operations:**

```python
# Register change at queue position
register_change(change_id, position)

# Calculate which changes must be in merge base
calculate_merge_base_position(change_id, queue)
  → Returns position → all earlier changes included

# Cascade failures to dependent changes
notify_dependents_of_failure(failed_change_id)
  → Marks dependents as 'requeue_needed'
  → Returns list of affected changes

# Determine queue order respecting dependencies
get_queue_order(queue)
  → Topological sort
  → Ensures dependencies before dependents
```

**State Tracking:**
```redis
torri:change:{id}:dependencies
{
  change_id: "123",
  queue_position: 5,
  depends_on: [],           # Changes this depends on
  dependent_of: ["124"],    # Changes that depend on this
}
```

---

### 4. **MergeCoordinator** (`merge_coordinator.py`)

Handles merge validation, locking, and conflict detection.

**Key Operations:**

```python
# Acquire global merge lock for a pipeline
acquire_merge_lock(pipeline_id)
  → Only ONE scheduler can merge at a time
  → Timeout: 30 seconds

# Pre-merge validation checklist
validate_before_merge(change_id, gerrit_change)
  ├─ Test status: gate tests passed?
  ├─ Merge permissions: Code-Review >= +1?
  ├─ Still mergeable: no conflicts in repo?
  ├─ Dependencies: earlier changes merged?
  └─ Branch protection: meets rules?

# Store merge attempt results
record_merge_attempt(change_id, success, error)

# Track and limit retries
should_retry_merge(change_id, max_retries=3)
```

**State Tracking:**
```redis
torri:change:{id}:merge_state
{
  state: "pending|validating|merging|success|failed|conflict",
  details: {},
  timestamp: "2026-05-12T10:30:45Z",
}

torri:change:{id}:merge_attempts
{
  attempts: [
    { timestamp, success, error },
    ...
  ]
}
```

---

### 5. **SpeculativeMerger** (`speculative_merger.py`)

Calculates merge bases and detects conflicts.

**Key Operations:**

```python
# Calculate merge base for speculative testing
calculate_merge_base(change_id, queue_position, earlier_changes)
  → If position 0: use branch head
  → If position > 0: virtually merge all earlier changes
  → Returns: (merge_base_hash, applied_changes)

# Check if change merges cleanly on base
can_merge_speculatively(change_id, merge_base_hash)
  → Detects conflicts
  → Returns: (can_merge, conflict_reason)

# Rebase on new base when main branch changes
handle_rebase_needed(change_id, new_base, old_base)
  → Attempts rebase
  → Detects rebase conflicts
  → Returns: (rebase_success, reason)

# Store merge base for later reference
store_merge_base(change_id, merge_base_hash, applied_changes)
```

**State Tracking:**
```redis
torri:change:{id}:merge_base
{
  hash: "abc123def456...",
  applied_changes: ["100", "101", "102"],
}
```

---

## Complete State Machine

```
┌──────────────┐
│   QUEUED     │ Event received, in queue
└──────┬───────┘
       │ start_speculative_testing()
       ↓
┌──────────────────────────┐
│ TESTING (speculative)    │ Tests running with merge base
└──────┬───────────────────┘
       ↓
    Tests complete
       ├─────────────────────────────────┐
       ↓                                 ↓
┌─────────────────┐        ┌──────────────────┐
│  MERGE_READY    │        │    FAILED        │ Notify user
└────────┬────────┘        └────────┬─────────┘
         │                          │
         │ Validate                 │ Cascade to dependents
         ↓                          │
┌─────────────────────┐             │
│ Pre-merge validation │ FAIL ──────┼─→ HOLD
│ (perms, conflicts)  │              
└────────┬────────────┘              
         │ PASS                      
         ↓                           
┌───────────────────────┐            
│  MERGING (lock held)  │ Merge operation in progress
└────────┬──────────────┘
         ↓
    Merge attempt
         ├──────────────────────────────┐
         ↓                              ↓
   ┌─────────────┐         ┌─────────────────────┐
   │   MERGED    │         │ RETEST_NEEDED       │ Main changed
   │  SUCCESS    │         │ (conflict detected) │
   └─────────────┘         └────────┬────────────┘
                                    │
                                    └─→ TESTING (restart)
```

---

## Example Flow: Two Changes in Parallel Gate

```
Time 0: Change A arrives
  → Position 0 in queue
  → Merge base = main branch
  → Start testing A on main

Time 1: Change B arrives  
  → Position 1 in queue
  → Merge base = main + A (speculative)
  → Can B merge on this base? Check conflicts
  → Start testing B on (main + A)

Time 60: A's tests pass
  → Mark A as MERGE_READY
  → Acquire merge lock
  → Merge A to main (actually merges)
  → Release lock
  → A now MERGED

Time 61: B's tests still running (but A just actually merged)
  → A's speculation was correct!
  → B's merge base assumption valid
  → Continue testing B

Time 120: B's tests pass
  → Mark B as MERGE_READY
  → Acquire merge lock
  → Merge B to main
  → Release lock
  → B now MERGED

Result: Tested in parallel (120s total), but merged serially (safe)
```

---

## Failure Cascade Example

```
Queue: [Change C, Change D, Change E]

C and D testing in parallel (speculative):
  D assumes C will merge

Time 60: C's tests FAIL

Action:
  1. Mark C as FAILED
  2. notification_dependents_of_failure(C)
  3. D marked as 'requeue_needed' (invalid merge base)
  4. E marked as 'requeue_needed' (depends on D)
  5. Cancel D's tests
  6. Cancel E's tests

Restart:
  7. C removed from queue
  8. Re-enqueue D (now position 0)
  9. Recalculate D's merge base (without C)
  10. Restart D's tests
  11. Once D passes, re-enqueue E
  12. Restart E's tests

Result: Cascade prevents invalid assumptions
```

---

## Merge Conflict Recovery Example

```
Initial state:
  Change A: merge base = commit abc123
  A's tests passed, ready to merge

Meanwhile:
  Someone else merges unrelated change Z to main
  Main branch now at commit xyz789

When A attempts merge:
  ✓ Merge validation checks if still mergeable
  ✗ Main changed (Z merged)
  
Action:
  1. Rebase A on new main (now includes Z)
  2. Mark A as RETEST_NEEDED
  3. New merge base = main + A (recalculate)
  4. Restart A's tests on new base
  5. If tests still pass → merge
  6. If tests fail → notify user

Result: Robustness to concurrent changes
```

---

## Multi-Scheduler Coordination

For running multiple scheduler instances:

**Duplicate Prevention:**
- Kafka consumer group ensures each change processed by ONE scheduler

**Merge Serialization:**
- Distributed merge lock (`torri:lock:merge:gate`)
- Only one scheduler can merge at a time
- Timeout: 30 seconds (prevents deadlock)

**State Visibility:**
- All state in Redis (shared)
- Each scheduler sees full queue and window state
- Window updates are atomic

---

## Testing Checklist

- [x] Module syntax validation
- [x] Integration with GatePipeline
- [x] Integration with SchedulerQueue
- [ ] Unit tests for each module
- [ ] Integration tests for full flow
- [ ] Failure cascade tests
- [ ] Merge conflict tests
- [ ] Multi-scheduler coordination tests
- [ ] Performance benchmarks

---

## Next Steps

1. **Implement executor/worker** to actually run jobs
2. **Connect to Gerrit API** for real merge operations
3. **Build monitoring/visualization** for queue state
4. **Add metrics** for queue depth, test duration, merge rates
5. **Performance tuning** for window sizing

---

## Notes

- Window size defaults to **1** (serial) for safety
- Can be increased in config for parallel gate testing
- Dynamic window adjustment not yet implemented
- Merge base calculation uses placeholder Git operations (MVP)
- Real implementation would use Git CLI or Gerrit API

