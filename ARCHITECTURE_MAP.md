# Zuul Architecture Map: Drivers, Connections, and System Design

This document explains how Zuul orchestrates multiple version control systems (SCMs) through a rigorous Object-Oriented architecture. The design respects the **Open-Closed Principle**, allowing engineers to add GitHub, GitLab, or Pagure without modifying core scheduler logic.

---

## 1. The Central Nervous System: ConnectionRegistry

At boot time, Zuul instantiates a **`ConnectionRegistry`** (in [zuul/lib/connections.py](zuul/lib/connections.py)). This registry is the **single point of orchestration** for all drivers, connections, sources, triggers, and reporters.

```python
class ConnectionRegistry(object):
    def __init__(self):
        self.connections = OrderedDict()
        self.drivers = {}

        # Boot Phase: Register all available drivers
        self.registerDriver(zuul.driver.gerrit.GerritDriver())
        self.registerDriver(zuul.driver.github.GithubDriver())
        self.registerDriver(zuul.driver.gitlab.GitlabDriver())
        # ... more drivers
```

At this point, **no** connections exist yet. The registry only knows about driver *classes/factories*. This is critical: the registry is **stateless at boot time**. No API tokens, no network connections have been established.

### Phase 1: Configuration Parsing
When the scheduler loads `zuul.conf`, the registry's `configure()` method reads sections like:

```ini
[connection gerrit]
driver = gerrit
canonical_hostname = gerrit.example.com
server = gerrit.example.com
port = 29418
sshkey = /home/zuul/.ssh/gerrit_key

[connection github]
driver = github
baseurl = https://github.com
app_id = 12345
private_key_file = /path/to/key
```

For each connection section, the registry:
1. Looks up the driver name (`driver = gerrit`)
2. Calls `self.drivers['gerrit'].getConnection(name, config)`
3. Stores the resulting **stateful** connection object in `self.connections['gerrit']`

**Key Insight:** At this moment, the `GerritConnection` object is created and instantiates its SSH client, loads keys, and opens network connections. It's no longer stateless—it *owns* the state.

---

## 2. Drivers: Stateless Factories

A **Driver** (e.g., `GerritDriver`, `GithubDriver`) is a **stateless factory** that knows how to manufacture three kinds of objects:
- **Connection**: The stateful network handler
- **Source**: The SCM abstraction layer
- **Trigger**: The event pattern matcher

Example from `GerritDriver`:
```python
class GerritDriver(BaseDriver):
    def getConnection(self, name, config):
        return GerritConnection(self, name, config)
    
    def getSource(self, connection):
        return GerritSource(connection)
    
    def getTrigger(self, connection, config):
        return GerritTrigger(connection, config)
```

**Design Pattern: Factory Method**
- The driver *never* holds state.
- The driver *never* contacts the external system.
- The driver is just a recipe: "Here's how to make a GerritConnection."

This allows Zuul to say: *"I want a Source for Gerrit"* without knowing anything about Gerrit's API details.

---

## 3. Connections: Stateful Network Heads

A **Connection** (e.g., `GerritConnection`, `GithubConnection`) is the **only object that talks to the external system**. It:
- Owns API tokens and SSH keys
- Maintains persistent sockets/HTTP sessions
- Caches data (in ZooKeeper or in-memory)
- Handles retries and backoff logic
- Converts external API payloads into Zuul's generic event format

### Multiple Concurrent Event Sources
A single `GerritConnection` can listen to *multiple event streams simultaneously*. For example:
```python
# In GerritConnection.__init__()
self.event_queue = queue.Queue()
self.watcher_thread = threading.Thread(target=self._watch_gerrit_stream)
self.watcher_thread.daemon = True
self.watcher_thread.start()
```

If configured with Kafka or Kinesis event streams, the connection spawns *additional* listener threads:
```python
if 'kafka_brokers' in config:
    self.kafka_thread = threading.Thread(target=self._watch_kafka)
    self.kafka_thread.daemon = True
    self.kafka_thread.start()

if 'kinesis_stream' in config:
    self.kinesis_thread = threading.Thread(target=self._watch_kinesis)
    self.kinesis_thread.daemon = True
    self.kinesis_thread.start()
```

All events (SSH, Kafka, Kinesis) are normalized into a single `ZuulTriggerEvent` and placed into the Scheduler's queue. **The scheduler has no idea which event stream produced the notification.**

---

## 4. Sources: The SCM Abstraction Layer

A **Source** (e.g., `GerritSource`, `GithubSource`) acts as a translator between the core scheduler and the external SCM's API. Its key methods include:

```python
class BaseSource(object):
    def getChange(self, event, project):
        """Convert an event into a rich Change object with all git metadata."""
        raise NotImplementedError
    
    def isMerged(self, change):
        """Ask the SCM: Is this change already merged?"""
        raise NotImplementedError
    
    def getRefSha(self, project, branch):
        """Ask the SCM: What is the current SHA of this branch?"""
        raise NotImplementedError
    
    def getMergeBase(self, project, branch1, branch2):
        """Ask the SCM: What is the common ancestor of these branches?"""
        raise NotImplementedError
```

**Critical Design Decision:** Every Source holds a **reference to its Connection**:

```python
class GerritSource(BaseSource):
    def __init__(self, connection):
        self.connection = connection
    
    def getChange(self, event, project):
        # Ask the connection to do the heavy lifting
        return self.connection.getChange(event, project)
```

Why not the other way around (Connection holds Source)? Because:
1. **Dependencies flow downward:** Core scheduler knows Projects, which know Sources. Sources delegate to Connections.
2. **Connections don't need to know about Sources:** They just provide raw git operations.
3. **Multiple Sources can share one Connection:** A `GerritSource` and a `GerritAuditSource` might both use the same `GerritConnection`.

---

## 5. Projects and Their Source Binding

In the Zuul configuration, every project is tied to a specific source:

```yaml
projects:
  - name: openstack/nova
    source: gerrit
    
  - name: kubernetes/kubernetes
    source: github
```

When Zuul loads the config, it creates `Project` objects and binds their `.source` attribute:

```python
class Project:
    def __init__(self, name, source_name, connection_registry):
        self.name = name
        # Polymorphic binding: Resolve source_name -> actual Source object
        self.source = connection_registry.getSource(source_name)
```

Now when a pipeline needs to ask *"Is nova merged?"*, it simply calls:
```python
if project.source.isMerged(change):
    # This call is dynamically routed to the correct subclass
    # GerritSource.isMerged() or GithubSource.isMerged()
```

**The scheduler has no hardcoded Gerrit or GitHub logic.** This is late-binding polymorphism.

---

## 6. Triggers: Event Pattern Matching (Decoupled from Core)

A **Trigger** decides whether an incoming event belongs to a specific pipeline. Examples:
- `GerritTrigger`: *"Run on patchset-created with Code-Review +1"*
- `GithubTrigger`: *"Run on pull_request opened or reopened"*
- `TimerTrigger`: *"Run every hour"*

Each pipeline has a list of triggers:

```python
class PipelineManager:
    def __init__(self, name, config):
        self.name = name
        self.triggers = []
        
        for trigger_config in config.get('trigger'):
            connection_name = trigger_config.get('connection')
            connection = registry.connections[connection_name]
            trigger = connection.driver.getTrigger(connection, trigger_config)
            self.triggers.append(trigger)
```

When an event arrives, the scheduler asks each trigger:

```python
def process_trigger_event(self, event):
    for pipeline in self.pipelines:
        for trigger in pipeline.triggers:
            if trigger.matches(event):
                # Route event into this pipeline's queue
                pipeline.enqueue_event(event)
                break
```

**Why is this decoupled?** The scheduler never asks: *"Is this a Gerrit event with Code-Review +1?"* Instead, it asks the `GerritTrigger` object, which encapsulates all Gerrit-specific logic. To add GitLab, you only add a `GitlabTrigger` class; the scheduler remains unchanged.

---

## 7. Reporters: Two-Phase Feedback (Also Decoupled)

A **Reporter** posts results back to the SCM. It's similar to Triggers but in reverse:

```python
class BaseReporter:
    def report(self, item, phase1=False, phase2=False):
        raise NotImplementedError
```

Each pipeline has reporters:

```python
class PipelineManager:
    def __init__(self, name, config):
        # ...
        self.reporters = []
        for reporter_config in config.get('reporter'):
            connection_name = reporter_config.get('connection')
            connection = registry.connections[connection_name]
            reporter = connection.driver.getReporter(connection, reporter_config)
            self.reporters.append(reporter)
```

When tests complete, the pipeline runs phase1 and phase2 reporters:

```python
def report_result(self, item, result):
    for reporter in self.reporters:
        reporter.report(item, phase1=True)
    
    # Later, after all phase1 reporters finish:
    for reporter in self.reporters:
        reporter.report(item, phase2=True)
```

**Two-Phase Design:** `phase1` posts lightweight feedback (comments), while `phase2` performs heavy operations (git merges, label changes). If a system fails mid-phase1, phase2 reporters don't fire, preventing inconsistent states.

---

## 8. How the Scheduler Stays Consistent (Respecting Open-Closed Principle)

The Zuul scheduler maintains consistency across all SCMs by **never being tightly coupled** to any specific one:

### Rule 1: Reverse Dependency
- Scheduler ← Pipelines ← Projects ← Sources ← Connections
- Connections never import or reference the Scheduler.
- Adding a new Connection (e.g., Pagure) doesn't require touching scheduler code.

### Rule 2: Polymorphic Dispatch
> "If I need to ask a question about a change, I ask the Source. The Source knows how to translate my question into the appropriate API call."

```python
# Inside PipelineManager (scheduler code)
if project.source.isMerged(change):  # OCP: Works for all SCMs
    # Don't know if this was Gerrit or GitHub
    # Don't care. The right method was called.
```

### Rule 3: Registry as the Hub

Instead of the Scheduler reaching into `zuul.driver.gerrit`, it asks the registry:

```python
# Good (respects OCP):
source = self.connection_registry.getSource('gerrit')

# Bad (violates OCP):
import zuul.driver.gerrit
source = zuul.driver.gerrit.GerritSource(...)
```

The registry always returns the correct polymorphic type.

### Rule 4: Configuration Drives Behavior

At boot, the config file tells Zuul *which* drivers to activate and *how many* connections:

```ini
[connection gerrit]
driver = gerrit

[connection github]
driver = github

[connection gitlab]
driver = gitlab
```

The scheduler doesn't hardcode this. It reads the config and asks the registry to instantiate connections. To add Pagure, you add a section and register the `PagureDriver`—no changes to scheduler code.

---

## 9. Day in the Life of a Gerrit Patchset


### Phase 1: Event Ingestion (Connection Layer)
A developer pushes code. Gerrit emits a `patchset-created` event over its SSH stream.

**What Happens:**
1. The `GerritConnection` has been listening on the SSH stream (thread running in background).
2. It receives the raw JSON: `{"type": "patchset-created", "change": {"number": 42, ...}}`
3. It normalizes this into a `ZuulTriggerEvent(project='nova', branch='master', ...)`
4. It writes this event to ZooKeeper's `tenant_trigger_events` queue.

**How This Respects OCP:**
- The Scheduler doesn't know events come from Gerrit's SSH.
- The Scheduler doesn't know the format of Gerrit JSON.
- If we swapped Gerrit for Pagure, the Scheduler would never notice.
- Only the `GerritConnection` understands Gerrit's event format.

---

### Phase 2: Scheduler Wakes and Decides

The Scheduler (`zuul/scheduler.py`) is sleeping, waiting on a `threading.Event()`. When ZooKeeper detects a new trigger event, it signals the scheduler:

```python
def process_trigger_queues(self):
    while True:
        event = self.connection_registry.get_next_trigger_event()
        
        # Ask each pipeline's triggers: "Is this yours?"
        for pipeline in self.pipelines:
            for trigger in pipeline.triggers:
                if trigger.matches(event):
                    # Yes! Route the event
                    pipeline.enqueue_change(event)
                    break
```

**Why Triggers Are in Pipelines (Not in Connections):**
- A Gerrit connection can fire hundreds of events (pushes, comments, votes).
- But the `check` pipeline might only care about `patchset-created`.
- The `gate` pipeline might only care about events with `Code-Review +2`.
- By putting Triggers in Pipelines, each pipeline independently decides which events it processes.

---

### Phase 3: Lazy Source Integration (The Polymorphic Leap)

The pipeline now needs rich git metadata. It calls:

```python
change = project.source.getChange(event, project)
```

**What polymorphism does here:**

For "nova" (Gerrit source):
```python
# In GerritSource.getChange()
self.connection.getChange(event)  # Hit Gerrit API
return GerritChange(...)
```

For "kubernetes" (GitHub source):
```python
# In GithubSource.getChange()
self.connection.getPullRequest(event)  # Hit GitHub API
return GithubChange(...)
```

The pipeline execution code calls the exact same line, but different `source.getChange()` methods fire. The scheduler never knew which one it was. **This is the genius of polymorphism in action.**

---

### Phase 4: Speculative Execution (Dependent Pipeline Manager)

If this patchset has a `Depends-On` header pointing to another patchset (#99), the `DependentPipelineManager` reads this and intelligently orders the tests:

```python
def process_item(self, item):
    # Read the Change object to extract dependencies
    dependencies = item.change.getDependencies()
    
    # Ensure foundational changes test first
    if dependencies:
        item_to_merge_on = self.find_root_change()
        cmd = f"git merge {item_to_merge_on.sha} {item.change.sha}"
        # Tell executor to test this merged state
```

The executor checks out both commits, merges them, and runs the test suite on the combined result. If the root commit fails, Zuul instantly orphans this patchset and re-tests it in isolation.

**Architectural Decision Made Here:** Why speculate? Because in a gate pipeline with 20 queued changes, if you wait for each to finish sequentially, you waste 19×test_time. By speculatively merging and testing, you get feedback in parallel. If a merge fails or a dependency breaks, Zuul's dequeue algorithms instantly correct course.

---

### Phase 5: Two-Phase Reporting (Reporter Layer)

Tests pass. The pipeline invokes its reporters:

```python
def report_pipeline_result(self, item, success):
    for reporter in self.reporters:
        reporter.report(item, phase1=True, message="Tests passed!")
    
    # If phase1 succeeded:
    for reporter in self.reporters:
        reporter.report(item, phase2=True, submit=True)
```

**Phase 1 (GerritReporter):**
```python
def report(self, item, phase1=False, phase2=False):
    if phase1:
        # Light, reversible operation
        self.connection.review(
            change_id, 
            message="Zuul: Tests passed", 
            labels={'Code-Review': '+1'}
        )
```

**Phase 2 (GerritReporter):**
```python
    if phase2:
        # Heavy, irreversible operation
        self.connection.review(
            change_id,
            submit=True  # Tells Gerrit to execute the merge
        )
```

**Why Two Phases?**
- Phase 1 reaches the Gerrit server, posts the comment.
- If Gerrit crashes mid-transaction, the comment is safely persisted.
- Phase 2 then executes the actual git merge.
- If Phase 2 fails, Phase 1 feedback is never lost.

**How does submission work?** When `submit=True`, the `GerritReporter` calls `self.connection.review()`, which constructs the SSH command:

```python
cmd = 'gerrit review --project nova --submit <changeid>'
self.connection._ssh(cmd)
```

The `GerritConnection` executes this over its persistent SSH connection to the Gerrit server. Gerrit then merges the change into the target branch.

---

## 10. Multiple Connections, Single Scheduler (Scaling Out)

Here's where the architecture really shines. Suppose Zuul is configured with three Gerrit servers *and* GitHub:

```ini
[connection gerrit1]
driver = gerrit
server = gerrit1.example.com

[connection gerrit2]
driver = gerrit
server = gerrit2.example.com

[connection gerrit3]
driver = gerrit
server = gerrit3.example.com

[connection github]
driver = github
baseurl = https://github.com
```

The ConnectionRegistry instantiates four Connection objects. Each connection has its own network threads listening to events independently. Events from all four stream into the same Scheduler's queue.

```python
# In Scheduler
def process_trigger_queues(self):
    for event in self.connection_registry.all_trigger_events():
        # Events might come from gerrit1, gerrit2, gerrit3, or github
        # Scheduler doesn't care
        for pipeline in self.pipelines:
            for trigger in pipeline.triggers:
                if trigger.matches(event):
                    pipeline.enqueue(event)
```

**How does the trigger know which connection it belongs to?**

```python
class GerritTrigger:
    def __init__(self, connection, config):
        self.connection = connection
        self.connection_name = connection.name  # 'gerrit1', 'gerrit2', etc.
    
    def matches(self, event):
        # Only process events from my connection
        if event.connection_name != self.connection_name:
            return False
        
        if event.type != 'patchset-created':
            return False
        
        return True
```

Now imagine you want to add a fourth Gerrit server. You:
1. Add `[connection gerrit4]` to the config
2. Restart Zuul
3. The ConnectionRegistry calls `GerritDriver.getConnection('gerrit4', config)`
4. A new `GerritConnection` object is born and starts listening
5. Existing pipelines that didn't reference gerrit4 continue working unchanged

**The scheduler never changes.** This is the Open-Closed Principle in production.

---

## 11. OOP Design Strategies Employed

### Strategy 1: Factory Pattern (Drivers)
Drivers are stateless factories. Each driver knows how to manufacture Connections, Sources, Triggers, and Reporters.

**Benefit:** The Scheduler doesn't instantiate objects directly. It asks the registry, which asks the driver. Adding a new driver means writing one class that implements the factory interface.

### Strategy 2: Dependency Injection
When a Connection is created, the driver passes `self` (the driver) to the connection:

```python
class GerritDriver:
    def getConnection(self, name, config):
        return GerritConnection(self, name, config)  # Driver is passed in
```

Later, when the connection needs a Source:
```python
class GerritConnection:
    def getSource(self):
        return self.driver.getSource(self)  # Ask driver to create source
```

Sources then hold a reference to the connection:
```python
class GerritSource:
    def __init__(self, connection):
        self.connection = connection  # Back-reference for API calls
```

**Benefit:** Objects are loosely coupled. No global imports. Easy to test (mock the driver/connection).

### Strategy 3: Registry Pattern
`ConnectionRegistry` acts as a service locator. Instead of importing `zuul.driver.gerrit` everywhere, code asks the registry:

```python
source = registry.getSource('gerrit')
reporter = registry.getReporter('github', pipeline)
```

**Benefit:** Decouples code from implementation details. Switching drivers means changing config, not code.

### Strategy 4: Abstract Base Classes (Polymorphism)
All Triggers inherit from `BaseTrigger`, all Sources from `BaseSource`, all Reporters from `BaseReporter`.

```python
class BaseSource(ABC):
    @abstractmethod
    def getChange(self, event, project):
        pass
    
    @abstractmethod
    def isMerged(self, change):
        pass
```

When the scheduler calls `project.source.isMerged(change)`, Python's method resolution finds the correct subclass implementation at runtime.

**Benefit:** The scheduler can work with *any* source without knowing specifics. Adding Pagure is just implementing `PagureSource` with these abstract methods.

### Strategy 5: Reverse Dependency / Dependency Inversion
- Connections import nothing from the Scheduler.
- The Scheduler imports Connections *only through the Registry*.
- Pipelines import Triggers *only through Drivers*.

**Benefit:** High-level modules (Scheduler) don't depend on low-level details (Gerrit API). Low-level modules (Connections) depend on abstractions (BaseConnection). This allows you to ship a new Connection without shipping a new Scheduler.

### Strategy 6: Two-Phase Operations
Reporters, managers, and executors use two-phase commits:
- **Phase 1:** Light, reversible feedback (comments, labels)
- **Phase 2:** Heavy, irreversible actions (merges, deletions)

**Benefit:** If any phase fails, earlier phases are safely committed and won't be orphaned.

---

## Summary

Zuul's architecture achieves consistency across multiple SCMs through:

1. **ConnectionRegistry** as a central hub that instantiates drivers and manages connections
2. **Drivers** as stateless factories that don't know about the Scheduler
3. **Connections** as the only objects that touch external APIs
4. **Sources** as polymorphic translators between generic questions and SCM-specific answers
5. **Triggers and Reporters** as decoupled pattern matchers and feedback channels
6. **Pipelines** as orchestrators that never embed SCM-specific logic

The **Open-Closed Principle** is maintained by ensuring:
- Core scheduler code never imports driver-specific modules
- All SCM integration happens through abstract base classes
- Configuration drives which drivers/connections are active
- Adding Pagure or Gitea requires adding a driver package, not modifying any pipeline logic

The **result:** A scheduler that can manage Gerrit, GitHub, GitLab, and custom Git repositories—today and in the future—without modification.