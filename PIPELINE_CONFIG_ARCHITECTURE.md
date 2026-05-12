# Pipeline Configuration System - Complete Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE CONFIGURATION SYSTEM                │
│                     YAML-Driven Pipeline Control                │
└─────────────────────────────────────────────────────────────────┘

┌────────────────────┬──────────────────┬────────────────────────┐
│  CONFIGURATION     │   VALIDATION     │    ORCHESTRATION       │
├────────────────────┼──────────────────┼────────────────────────┤
│ PipelineConfig     │ PipelineRequire- │ PipelineEntryGate      │
│                    │ mentValidator    │                        │
│ • Parse YAML       │                  │ • Auto-validate        │
│ • Label normaliz.  │ • Check approvals│ • Post comments        │
│ • Message support  │ • Check rejects  │ • Orchestrate flow     │
│                    │ • Query Gerrit   │                        │
│                    │ • Post messages  │                        │
├────────────────────┼──────────────────┼────────────────────────┤
│ PipelineConfigLoad │                  │                        │
│                    │                  │                        │
│ • Load YAML file   │                  │                        │
│ • Expose pipelines │                  │                        │
└────────────────────┴──────────────────┴────────────────────────┘

↓ Integrates with existing Gate System ↓

┌────────────────────────────────────────────────────────────────┐
│            UNIFIED REF PIPELINE MANAGER                         │
├────────────────────────────────────────────────────────────────┤
│ • Change state tracking (Check, Gate, Report pipelines)        │
│ • Synthetic ref management for testing                         │
│ • Dependency blocking logic                                    │
└────────────────────────────────────────────────────────────────┘

↓ Executes using ↓

┌────────────────────────────────────────────────────────────────┐
│            GATE ALGORITHM EXECUTOR                              │
├────────────────────────────────────────────────────────────────┤
│ • Phase 1: Check pipeline (speculative test on synthetic ref)  │
│ • Phase 2: Gate pipeline (actual submit to Gerrit)             │
│ • Phase 3: Report pipeline (post-merge actions)                │
└────────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram

```
GERRIT EVENT (patchset created)
         │
         ▼
    change #12345
    patchset 1
         │
         ▼
┌─────────────────────────────────────────┐
│ PipelineEntryGate                       │
│ check_and_enter_pipeline()              │
│                                         │
│ 1. Load PipelineConfig from YAML        │
│    → config = {                         │
│    →   name: 'check',                   │
│    →   required: {Code-Review: 2, ...}  │
│    → }                                  │
├─────────────────────────────────────────┤
│ 2. Query Gerrit for change details      │
│    gerrit_conn.query(12345)             │
│    → {status: NEW, labels: {...}}       │
├─────────────────────────────────────────┤
│ 3. Validate requirements in validator   │
│    validator.can_enter_pipeline(...)    │
│    → Check: open? ✅                    │
│    → Check: approvals? ✅               │
│    → Check: rejections? ✅              │
├─────────────────────────────────────────┤
│ 4. Post Gerrit comment                  │
│    if PASS: start-message               │
│    if FAIL: rejection reason            │
└─────────────────────────────────────────┘
         │
    ┌────┴────┐
    │          │
✅ PASS   ❌ FAIL
    │          │
    ▼          ▼
CONTINUE    STOP
    │    (comment
    │     posted)
    ▼
(Continue to Gate Algorithm execution)
```

## Class Relationships

```
┌──────────────────────────────────────────────────────────────┐
│                    PipelineConfigLoader                       │
│                          (singleton)                          │
├──────────────────────────────────────────────────────────────┤
│ • Loads YAML file once at startup                            │
│ • Maintains dict of PipelineConfig objects                   │
│ • Exposes get_pipeline() and get_all_pipelines()             │
└──────────────────────────────────────────────────────────────┘
              ▲
              │ creates
              │
┌──────────────────────────────────────────────────────────────┐
│                    PipelineConfig (1...N)                     │
├──────────────────────────────────────────────────────────────┤
│ • Represents single pipeline from YAML                       │
│ • Parses approvals, rejections, messages                     │
│ • Normalizes label names                                     │
└──────────────────────────────────────────────────────────────┘


┌──────────────────────────────────────────────────────────────┐
│               PipelineEntryGate (uses)                        │
├──────────────────────────────────────────────────────────────┤
│ • Orchestrates entry flow                                    │
│ • Delegates to validator                                     │
│ • Posts Gerrit comments                                      │
└──────────────────────────────────────────────────────────────┘
         ▲              ▲
         │ reads        │ uses
         │              │
     Config Loader      │
                        ▼
             ┌────────────────────────────┐
             │ PipelineRequirement        │
             │ Validator (injected)       │
             ├────────────────────────────┤
             │ • Validates change         │
             │ • Queries Gerrit           │
             │ • Posts messages           │
             └────────────────────────────┘
```

## Component Responsibilities

```
PipelineConfig
├─ Parse YAML dict → object attributes
├─ Normalize label names (code-review → Code-Review)
├─ Parse approval lists → dict
├─ Parse rejection lists → dict
└─ Support message fields

PipelineConfigLoader
├─ Read YAML file
├─ Create PipelineConfig for each pipeline
├─ Store in dict
├─ Expose via get_pipeline(name) and get_all_pipelines()
└─ Handle YAML errors

PipelineRequirementValidator
├─ Query Gerrit for change details
├─ Validate: open status ✓
├─ Validate: current patchset ✓
├─ Validate: required approvals ✓
├─ Validate: no rejections ✓
├─ Post start-message to Gerrit
├─ Post rejection reason to Gerrit
└─ Return (can_enter: bool, reason: str)

PipelineEntryGate
├─ Load pipeline config
├─ Call validator
├─ Return result + message
└─ Orch​estrate from entry to execution
```

## YAML Processing Pipeline

```
pipelines.yaml
       │
       ▼
[Loader opens file]
       │
       ▼
[yaml.safe_load()]
       │
       ├─ pipelines:
       │    └─ [list of pipeline dicts]
       │
       ▼
[For each pipeline dict]
       │
       ├─ Create PipelineConfig(dict)
       │    │
       │    ├─ Parse name, manager
       │    ├─ Parse require/reject/success/failure
       │    ├─ Normalize label names
       │    │    code-review → Code-Review
       │    │    verified → Verified
       │    └─ Create approval/rejection dicts
       │
       ├─ Store in loader.pipelines dict
       │    loader.pipelines['check'] = config
       │    loader.pipelines['gate'] = config
       │
       ▼
[Ready for use]
```

## Validation Logic Flow

```
can_enter_pipeline(change_id, patchset, pipeline_name, config)
│
├─ Query Gerrit for change details
│  └─ change_data = gerrit_conn.query(change_id)[0]
│
├─ Check 1: Is change OPEN?
│  │  status = change_data['status']
│  │  if status != 'NEW'
│  │     ❌ FAIL: "Change is {status}, not open"
│  │
│  └─ ✅ PASS
│
├─ Check 2: Current patchset?
│  │  current_revision = change_data['current_revision']
│  │  if not current_revision
│  │     ❌ FAIL: "Cannot determine current patchset"
│  │
│  └─ ✅ PASS
│
├─ Check 3: No rejected labels?
│  │  For each label in config.reject_approvals
│  │     value = change_data['labels'][label]['value']
│  │     if value in rejected_values
│  │        ❌ FAIL: "Label '{label}' has rejected value {value}"
│  │
│  └─ ✅ PASS (none found)
│
├─ Check 4: All required approvals present?
│  │  For each label in config.required_approvals
│  │     if label not in change_data['labels']
│  │        ❌ FAIL: "Missing required label '{label}'"
│  │
│  │     if value < required_value
│  │        ❌ FAIL: "Label value is {value}, needs {required}"
│  │
│  └─ ✅ PASS (all present and sufficient)
│
└─ ✅ PASS (all checks passed)
   Return (True, None)
```

## Label Normalization Algorithm

```
input: "code-review"
│
├─ Split by hyphen
│  └─ ['code', 'review']
│
├─ Capitalize each part
│  ├─ 'code' → 'Code'
│  └─ 'review' → 'Review'
│
├─ Join with hyphen
│  └─ 'Code' + '-' + 'Review'
│
└─ output: "Code-Review" ✅

Examples:
  "verified" → ['verified'] → ['Verified'] → "Verified"
  "integrated" → ['integrated'] → ['Integrated'] → "Integrated"
  "my-custom-label" → ['my', 'custom', 'label'] → ['My', 'Custom', 'Label'] → "My-Custom-Label"
```

## Integration with Gate Algorithm

```
             PipelineEntryGate
                    │
    ┌───────────────┼───────────────┐
    │               │               │
    ▼               ▼               ▼
  check          gate            post
 pipeline      pipeline        pipeline
    │               │               │
    │(Validate)     │(Validate)     │(Validate)
    ▼               ▼               ▼
   ENTRY          ENTRY           ENTRY
   (comment)      (comment)       (comment)
    │               │               │
    │(if PASS)      │(if PASS)      │(if PASS)
    ▼               ▼               ▼
UnifiedRefPipelineManager
    │
    ├─ Enqueue change
    ├─ Request synthetic ref
    └─ Track state
        │
        ▼
    GateAlgorithm.execute()
    (5-phase execution)
        │
        ▼
    Post success/failure labels
    to Gerrit
        │
        ▼
    Update state:
    'NOT_STARTED' → 'PROCESSING' → 'SUCCESS'/'FAILED'
```

## State Machine

```
┌─────────────────────────────────────────────────────┐
│         CHANGE LIFECYCLE THROUGH PIPELINES          │
└─────────────────────────────────────────────────────┘

                                    ← Patchset created
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │ CHECK Pipeline Entry │
                        │ (PipelineEntryGate)  │
                        └──────────────────────┘
                                    │
                            ┌───────┴────────┐
                            │                │
                        ✅ PASS         ❌ FAIL
                            │                │
                            ▼                ▼
                        ┌────────┐    Posted rejection
                        │ Enqueue│    comment to Gerrit
                        │ Change │    │
                        └────────┘    │
                            │         │
                            ▼         │
                        ┌──────────────────────┐
                        │ CHECK Pipeline Exec  │  (if previous FAILED, stop)
                        │ (GateAlgorithm)      │
                        │ • Test on synthetic  │
                        │ • Post labels        │
                        └──────────────────────┘
                                    │
                            ┌───────┴────────┐
                            │                │
                        ✅ SUCCESS      ❌ FAILED
                            │                │
                            ▼                ▼
                        ┌──────────────────────┐
                        │ GATE Pipeline Entry  │  Check failed - stop
                        │ (PipelineEntryGate)  │
                        └──────────────────────┘
                                    │
                            ┌───────┴────────┐
                            │                │
                        ✅ PASS         ❌ FAIL
                            │                │
                            ▼                ▼
                        ┌────────┐    Posted rejection
                        │ Ready  │    comment to Gerrit
                        └────────┘
                            │
                            ▼
                        ┌──────────────────────┐
                        │ GATE Pipeline Exec   │
                        │ (GateAlgorithm)      │
                        │ • SUBMIT to Gerrit   │
                        │ • Post labels        │
                        └──────────────────────┘
                                    │
                            ┌───────┴────────┐
                            │                │
                        ✅ MERGED        ❌ FAILED
                            │                │
                            ▼                ▼
                        ┌──────────────────────┐
                        │ POST Pipeline Entry  │  Gate failed - stop
                        │ (PipelineEntryGate)  │
                        └──────────────────────┘
                                    │
                        ┌───────────┴────────────┐
                        │                        │
                    ✅ PASS              ❌ FAIL
                        │                        │
                        ▼                        ▼
                    POST exec              Done
                    │                       │
                    ▼                       ▼
              ✅ COMPLETE             ✅ COMPLETE
                                      (with failure)
```

## File Dependencies

```
New Code:

pipeline_config.py (550 lines)
  ├─ Imports:
  │   ├─ yaml (PyYAML)
  │   ├─ shared.logger_setup (existing)
  │   └─ Standard library only
  │
  ├─ Classes:
  │   ├─ PipelineConfig
  │   ├─ PipelineConfigLoader
  │   ├─ PipelineRequirementValidator
  │   └─ PipelineEntryGate
  │
  └─ Exports via: scheduler/__init__.py

Integration Points:

Existing Code Used:
  ├─ gerritconnection.py
  │   ├─ .query(change_id)
  │   ├─ .set_review(change_id, patchset, message, labels)
  │   └─ .submit_change(change_id)
  │
  ├─ ref_pipeline_manager.py
  │   ├─ .enqueue_change()
  │   ├─ .request_synthetic_ref()
  │   ├─ .can_pipeline_process()
  │   └─ .update_pipeline_state()
  │
  └─ gate_algorithm.py
      └─ .execute(change_id, patchset, pipeline_name)

Configuration File:
  └─ src/torri/config/layout/pipelines.yaml
```

## Deployment Steps

```
1. Deploy Code
   └─ Copy pipeline_config.py to src/torri/scheduler/
   └─ Update scheduler/__init__.py exports

2. Verify Imports
   └─ python3 -c "from torri.scheduler import PipelineEntryGate"

3. Test with YAML
   └─ loader = PipelineConfigLoader('pipelines.yaml')
   └─ gate = PipelineEntryGate(gerrit_conn, loader)

4. Deploy in Gate Service
   └─ Initialize in startup
   └─ Use in patchset-created handler
   └─ Monitor logs for errors

5. Monitor
   └─ Check Gerrit comments posted
   └─ Verify labels set correctly
   └─ Monitor for validation errors
```

## Summary

**New System = YAML Configuration + Validation + Orchestration**

```
                    pipelines.yaml
                         │
                         ▼
         ┌──────────────────────────────┐
         │ PipelineConfigLoader         │
         │ (loads YAML once)            │
         └──────────────────────────────┘
                         │
         ┌──────────────┴─────────────┐
         │                            │
         ▼                            ▼
    config_loader         ┌──────────────────────┐
                          │ PipelineEntryGate    │
                          │ (orchestrates entry) │
                          └──────────────────────┘
                                     │
                          ┌──────────┴──────────┐
                          │                     │
                    ✅ PASS              ❌ FAIL
                          │                     │
                          ▼                     ▼
                    GateAlgorithm         Gerrit comment
                     .execute()            (rejection)
                          │
                    Posted labels
                          │
                    ✅ COMPLETE
```

---

**For quick usage:** PIPELINE_CONFIG_QUICK_REFERENCE.md
**For implementation:** PIPELINE_CONFIG_GUIDE.md
**For examples:** EXAMPLE_PIPELINE_INTEGRATION.py
