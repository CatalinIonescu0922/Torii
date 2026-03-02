"""
Main Entry Point for Events Consumer Intelligence Layer
Orchestrates the three-layer architecture
"""
import sys
from typing import Optional, Tuple
from pydantic import ValidationError

from kafka_client import KafkaEventConsumer
from events import route_event
from shared.model import (
    PatchSetCreatedEvent,
    CommentAddedEvent,
    ChangeMergedEvent,
    DraftPublishedEvent,
    RoutingDecision
)

from shared.logger_setup import (
    setup_logging, 
    get_logger, 
    log_context, 
    correlation_context,
    register_signal_handlers
)
from shared.layout_validator import Validator

setup_logging(service_name="EventsConsumer")
logger = get_logger(__name__)

#get the layout_data and also validate the layout files 
layouts_data=Validator.validateAllFiles()

def process_gerrit_event(event_data: dict) -> Tuple[bool, Optional[str]]:
    """
    Main processing pipeline: Validation → Routing → Decision
    
    Args:
        event_data: Raw Gerrit event JSON
        
    Returns:
        (should_process, reason) tuple
    """
    event_type = event_data.get("type", "unknown")
    
    # Use correlation context for tracking this event across all logs
    with correlation_context() as correlation_id:
        # Add structured logging context
        with log_context(event_type=event_type):
            logger.debug("Starting event processing with correlation_id: %s", correlation_id)
            
            try:
                # Step 1: Validate event (Layer B)
                validated_event = validate_event(event_data , layouts_data.get("projects_data"))
                
                if not validated_event:
                    logger.warning("Skipping unknown event type: %s", event_type)
                    return (False, None)
                
                # Step 2: Route to handler (Layer C)
                decision: RoutingDecision = route_event(validated_event)
                
                # Step 3: Handle decision
                if decision.action == "PROCESS":
                    logger.info("✓ Event processed: %s", decision.reason)
                    return (True, decision.reason)
                
                elif decision.action == "IGNORE":
                    logger.debug("⊘ Event ignored: %s", decision.reason)
                    return (False, None)
                
                elif decision.action == "ERROR":
                    logger.error("✗ Event error: %s", decision.reason)
                    return (False, None)
            
            except ValidationError as e:
                logger.warning("Validation failed for %s: %s", event_type, e)
                return (False, None)
            
            except Exception as e:
                logger.error("Unexpected error processing %s: %s", event_type, e, exc_info=True)
                return (False, "Unexpected error")
            
            return (False, "No action taken")

def filter_events(event_data : dict , projects_data):
    """
    Filter any raw events that may come from gerrit 

    
    :param event_data: Description
    :type event_data: dict
    """
    if event_data.get("type") == 'ref-updated':
        return None
    else:
        return event_data
def validate_event(event_data: dict, projects_data : dict):
    """
    Validates raw event JSON against Pydantic models.
    
    Returns:
        Validated Pydantic model or None
    """
    filter_events(event_data, projects_data)
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
        logger.warning("Validation error for %s: %s", event_type, e)
        raise

def main():
    """Start the Events Consumer Intelligence Layer"""    
    # Register signal handlers for config reload (Unix only)
    register_signal_handlers()
    
    logger.info("Events Consumer Intelligence Layer - Starting")

    # Initialize Kafka client
    kafka_client = KafkaEventConsumer()
    
    try:
        # Connect to Kafka
        kafka_client.connect()
        # Start consumption loop
        kafka_client.consume_and_process(process_gerrit_event)

    except KeyboardInterrupt:
        logger.info("Received shutdown signal (Ctrl+C)")
    
    except Exception as e:
        logger.critical("Fatal error occurred: %s", e, exc_info=True)
        sys.exit(1)
    
    finally:
        logger.info("Events Consumer Intelligence Layer - Stopped")


if __name__ == "__main__":
    main()
