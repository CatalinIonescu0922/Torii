# Events Consumer - Intelligence Layer

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your Kafka settings
   ```

3. **Run the service:**
   ```bash
   python main.py
   ```

## Architecture

### Three-Layer Design:
- **Layer A (Transport):** `kafka_client.py` - Kafka consumer/producer
- **Layer B (Validation):** `shared/model.py` - Pydantic models
- **Layer C (Logic):** `events.py` - Event router & handlers

## Configuration

Edit `events.py` → `Config` class to customize:

```python
Config.MONITORED_PROJECTS = ["my-repo", "core-api"]
Config.TRIGGER_ON_VERIFIED_PLUS_ONE = True
Config.TRIGGER_ON_CODE_REVIEW_PLUS_TWO = True
Config.REQUIRE_BOTH_LABELS = False
```

## Event Flow

1. Gerrit → Kafka (`gerrit-events` topic)
2. Consumer polls and deserializes
3. Pydantic validates structure
4. Handler decides: TRIGGER_BUILD / IGNORE / ERROR
5. If TRIGGER_BUILD → publish to `ci-internal-triggers`
6. Manual commit offset (at-least-once delivery)

## Supported Events

- `patchset-created` → Triggers on new uploads
- `comment-added` → Triggers on Verified+1 / Code-Review+2
- `change-merged` → Triggers post-merge jobs
- `draft-published` → Triggers like patchset-created

## Monitoring

Logs are written to:
- Console (stdout)
- `events_consumer.log` file

## Reliability Features

✓ Manual offset commit (no message loss)  
✓ Stateless (horizontal scaling)  
✓ Graceful shutdown (Ctrl+C)  
✓ Error recovery (bad messages are skipped)
