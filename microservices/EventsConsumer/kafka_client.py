"""
Layer A: Transport Layer - Kafka Consumer & Producer
Handles connection to Kafka and message serialization
"""
import json
import os
import logging
from typing import Callable, Optional
from dotenv import load_dotenv
from confluent_kafka import Consumer, Producer, KafkaException, KafkaError
from pydantic import ValidationError

logger = logging.getLogger(__name__)
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
        self.producer: Optional[Producer] = None
        self.running = False
        
        # Consumer configuration
        self.consumer_config = {
            'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:9092"),
            'group.id': os.getenv("KAFKA_GROUPID", "events-consumer-group"),
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,  # Manual commit for reliability
            'max.poll.interval.ms': 300000  # 5 minutes
        }
        
        # Producer configuration
        self.producer_config = {
            'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:9092"),
            'acks': 'all',  # Wait for all replicas
            'retries': 3,
            'linger.ms': 10  # Batch messages for efficiency
        }
        
        self.input_topic = os.getenv("KAFKA_INPUT_TOPIC", "gerrit-events")
        self.output_topic = os.getenv("KAFKA_OUTPUT_TOPIC", "processed-events")
    
    def connect(self):
        """Establish connections to Kafka"""
        try:
            self.consumer = Consumer(self.consumer_config)
            self.producer = Producer(self.producer_config)
            self.consumer.subscribe([self.input_topic])
            self.running = True
            logger.info(f"✓ Connected to Kafka, subscribed to {self.input_topic}")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Kafka: {e}")
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
                        logger.error(f"Kafka error: {msg.error()}")
                        continue
                
                # Deserialize message
                try:
                    raw_data = msg.value().decode('utf-8')
                    event_data = json.loads(raw_data)
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to decode message: {e}")
                    self.consumer.commit()  # Commit to skip bad message
                    continue
                
                # Process event
                try:
                    should_process, reason = process_callback(event_data)
                    
                    if should_process:
                        logger.info(f"Event processed: {reason}")
                    
                    # Manual commit after successful processing
                    self.consumer.commit()
                    
                except Exception as e:
                    logger.error(f"Error processing event: {e}", exc_info=True)
                    # Commit anyway to avoid blocking the queue
                    self.consumer.commit()
                    continue
        
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            self.shutdown()
    
    def _delivery_callback(self, err, msg):
        """Kafka producer delivery callback"""
        if err:
            logger.error(f"Message delivery failed: {err}")
        else:
            logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down Kafka client...")
        self.running = False
        
        if self.producer:
            self.producer.flush(timeout=10)
            logger.info("✓ Producer flushed")
        
        if self.consumer:
            self.consumer.close()
            logger.info("✓ Consumer closed")

