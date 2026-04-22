import os
import json
from typing import Optional, Any
from confluent_kafka import Producer
from shared.logger_setup import get_logger

class KafkaProducerClient:
    """
    A decoupled Kafka producer that can be imported to send messages to arbitrary topics.
    Configured with acks='all' for resilient delivery.
    """
    def __init__(self, bootstrap_servers: Optional[str] = None):
        self.logger = get_logger("torri.kafka.producer")
        servers = bootstrap_servers or os.getenv("KAFKA_SERVER", "localhost:9094")
        
        self.producer_config = {
            'bootstrap.servers': servers,
            'acks': 'all',  # Ensure all partition replicas acknowledge before marking as successful
            'retries': 5,
            'enable.idempotence': True # Prevents duplicates on retries
        }
        try:
            self.producer = Producer(self.producer_config)
            self.logger.info("Initialized Kafka Producer connected to %s", servers)
        except Exception as e:
            self.logger.error("Failed to initialize Kafka Producer: %s", e, exc_info=True)
            raise

    def _delivery_report(self, err, msg):
        """Called once for each message produced to indicate delivery result."""
        if err is not None:
            self.logger.error('Message delivery failed: %s', err)
        else:
            self.logger.debug('Message delivered to %s [%s] at offset %s',
                              msg.topic(), msg.partition(), msg.offset())

    def send_message(self, topic: str, key: str, value: dict[str, Any] | str):
        """
        Sends a message to the specified Kafka topic.
        
        Args:
            topic (str): The Kafka topic to produce to.
            key (str): The partitioning key (e.g., repository name to ensure locality).
            value (dict | str): The message payload.
        """
        if isinstance(value, dict):
            try:
                # Convert the value dict down to a JSON string then bytes
                payload = json.dumps(value).encode('utf-8')
            except TypeError as e:
                self.logger.error("Failed to serialize message value: %s", e)
                raise
        else:
            payload = value.encode('utf-8') if isinstance(value, str) else value

        try:
            # Produce the message
            self.producer.produce(
                topic=topic,
                key=key.encode('utf-8'),
                value=payload,
                callback=self._delivery_report
            )
            # Polls for delivery callbacks (asynchronously)
            self.producer.poll(0)
        except Exception as e:
            self.logger.error("Failed to enqueue message for topic %s: %s", topic, e)
            raise

    def flush(self, timeout: float = 10.0):
        """Ensure all messages are delivered before stopping."""
        self.logger.info("Flushing Kafka Producer...")
        self.producer.flush(timeout)
