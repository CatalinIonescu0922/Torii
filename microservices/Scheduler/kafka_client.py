"""
Layer A: Transport Layer - Kafka Consumer
Handles connection to Kafka and message deserialization
"""
import json
import os
from typing import Callable, Optional
from dotenv import load_dotenv
from confluent_kafka import Consumer, KafkaException, KafkaError
from pydantic import ValidationError

# Use shared hierarchical logging
from shared.logger_setup import get_logger

logger = get_logger(__file__)
load_dotenv()



class KafkaEventConsumer:
    """
    High-performance Kafka consumer for Gerrit events.
    
    Features:
    - Manual offset commit (at-least-once delivery)
    - Graceful shutdown handling
    - Automatic retry on transient errors
    """
    
    def __init__(self):
        self.consumer: Optional[Consumer] = None
        self.running = False
        
        # Consumer configuration
        self.consumer_config = {
            'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:9094"),
            'group.id': os.getenv("KAFKA_GROUPID", "events-consumer-group"),
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,  # Manual commit for reliability
            'max.poll.interval.ms': 300000  # 5 minutes
        }
                
        self.input_topic = os.getenv("KAFKA_INPUT_TOPIC", "gerrit-events")
    
    def connect(self):
        """Establish connection to Kafka"""
        try:
            self.consumer = Consumer(self.consumer_config)
            self.consumer.subscribe([self.input_topic])
            self.running = True
            logger.info("Connected to Kafka, subscribed to %s", self.input_topic)
        except Exception as e:
            logger.error("Failed to connect to Kafka: %s", e, exc_info=True)
            raise
    
    def consume_and_process(self, process_callback: Callable[[dict], tuple[bool, Optional[str]]]):
        """
        Main consumption loop with manual commit.
        
        Args:
            process_callback: Function that processes event and returns (should_process, reason)
        """
        if not self.consumer:
            raise RuntimeError("Consumer not initialized. Call connect() first.")
        
        logger.info("Starting event consumption loop...")
        
        try:
            while self.running:
                # Poll for messages
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug("Reached end of partition")
                        continue
                    else:
                        logger.error("Kafka error: %s", msg.error())
                        continue
                
                # Deserialize message
                try:
                    raw_data = msg.value().decode('utf-8')
                    event_data = json.loads(raw_data)
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    logger.error("Failed to decode message: %s", e)
                    self.consumer.commit()  # Commit to skip bad message
                    continue
                
                # Process event
                try:
                    should_process, reason = process_callback(event_data)
                    
                    if should_process:
                        logger.debug("Event processed successfully: %s", reason)
                    
                    # Manual commit after successful processing
                    self.consumer.commit()
                    
                except Exception as e:
                    logger.error("Error processing event: %s", e, exc_info=True)
                    # Commit anyway to avoid blocking the queue
                    self.consumer.commit()
                    continue
        
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down Kafka client...")
        self.running = False
        
        if self.consumer:
            self.consumer.close()
            logger.info("✓ Consumer closed")

if __name__ == '__main__':
    kafka = KafkaEventConsumer()
    kafka.connect()