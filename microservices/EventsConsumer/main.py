"""
Main Entry Point for Events Consumer Intelligence Layer
Orchestrates the three-layer architecture
"""
import logging
import sys
from typing import Optional, Tuple
from pydantic import ValidationError

sys.path.append('..')

from kafka_client import KafkaEventConsumer
from events import route_event
from shared.model import (
    PatchSetCreatedEvent,
    CommentAddedEvent,
    ChangeMergedEvent,
    DraftPublishedEvent,
    RoutingDecision
)

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('events_consumer.log')
    ]
)

logger = logging.getLogger(__name__)

def process_gerrit_event(event_data: dict) -> Tuple[bool, Optional[str]]:
    """
    Main processing pipeline: Validation → Routing → Decision
    
    Args:
        event_data: Raw Gerrit event JSON
        
    Returns:
        (should_process, reason) tuple
    """
    event_type = event_data.get("type", "unknown")
    
    try:
        # Step 1: Validate event (Layer B)
        validated_event = validate_event(event_data)
        
        if not validated_event:
            logger.warning(f"Skipping unknown event type: {event_type}")
            return (False, None)
        
        # Step 2: Route to handler (Layer C)
        decision: RoutingDecision = route_event(validated_event)
        
        # Step 3: Handle decision
        if decision.action == "PROCESS":
            logger.info(f"✓ Event processed: {decision.reason}")
            return (True, decision.reason)
        
        elif decision.action == "IGNORE":
            logger.debug(f"⊘ Event ignored: {decision.reason}")
            return (False, None)
        
        elif decision.action == "ERROR":
            logger.error(f"✗ Event error: {decision.reason}")
            return (False, None)
    
    except ValidationError as e:
        logger.warning(f"Validation failed for {event_type}: {e}")
        return (False, None)
    
    except Exception as e:
        logger.error(f"Unexpected error processing {event_type}: {e}", exc_info=True)
        return (False, "Unexpected error")
    
    return (False, "No action taken")

def filter_events(event_data : dict ):
    """
    Filter any raw events that may come from gerrit 

    
    :param event_data: Description
    :type event_data: dict
    """
    if event_data.get("type") == 'ref-updated':
        return None
    else:
        return event_data
def validate_event(event_data: dict):
    """
    Validates raw event JSON against Pydantic models.
    
    Returns:
        Validated Pydantic model or None
    """
    event_type = event_data.get("type")
    # Map event types to Pydantic models
    event_models = {
        "patchset-created": PatchSetCreatedEvent,
        "comment-added": CommentAddedEvent,
        "change-merged": ChangeMergedEvent,
        "draft-published": DraftPublishedEvent,
    }
    
    model_class = event_models.get(event_type)
    
    if event_type == "ref-updated":
        return None

    if not model_class:
        return None
    
    try:
        return model_class(**event_data)
    except ValidationError as e:
        logger.warning(f"Validation error for {event_type}: {e}")
        raise

def main():
    """Start the Events Consumer Intelligence Layer"""
    logger.info("=" * 60)
    logger.info("Events Consumer Intelligence Layer - Starting")
    logger.info("=" * 60)
    
    # Initialize Kafka client
    kafka_client = KafkaEventConsumer()
    
    try:
        # Connect to Kafka
        kafka_client.connect()
        
        # Start consumption loop
        kafka_client.consume_and_process(process_gerrit_event)
    
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    
    finally:
        logger.info("=" * 60)
        logger.info("Events Consumer Intelligence Layer - Stopped")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
