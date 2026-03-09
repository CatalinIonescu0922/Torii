import json
import os
from pathlib import Path
from typing import Callable, Optional
from dotenv import load_dotenv
from confluent_kafka import Consumer, KafkaException, KafkaError
from pydantic import ValidationError
from pathlib import Path
from shared.logger_setup import get_logger , setup_logging

config_path = Path("/home/cata/Desktop/Torii/microservices/Scheduler/config/log/main_logging.yaml")
work_dir = Path("/home/cata/Desktop/Torii/microservices/Scheduler/")
setup_logging(config_path , work_dir)
load_dotenv()

class KafkaConnection:
    """
    Keeps a running connection with Kafka
    reads any incomming messages and sends them to the approapiate structures 
    """
    logger = get_logger("Scheduler.kafka_connection")
    
    def __init__(self):
        self.consumer: Optional[Consumer] = None
        self.running = False
        
        # Consumer configuration
        self.consumer_config = {
            'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:90977"),
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
            self.logger.info("Connected to Kafka, subscribed to %s", self.input_topic)
        except Exception as e:
            self.logger.error("Failed to connect to Kafka: %s", e, exc_info=True)
            raise
    
    def consume_and_process(self, process_callback: Callable[[dict], tuple[bool, Optional[str]]]):
        """
        Main consumption loop with manual commit.
        """
        if not self.consumer:
            raise RuntimeError("Consumer not initialized. Call connect() first.")
        
        self.logger.info("Starting event consumption loop...")
        
        try:
            while self.running:
                # Poll for messages
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        self.logger.debug("Reached end of partition")
                        continue
                    else:
                        self.logger.error("Kafka error: %s", msg.error())
                        continue
                
                # Deserialize message
                try:
                    raw_data = msg.value().decode('utf-8')
                    event_data = json.loads(raw_data)
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    self.logger.error("Failed to decode message: %s", e)
                    self.consumer.commit()  # Commit to skip bad message
                    continue
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Shutting down Kafka client...")
        self.running = False
        
        if self.consumer:
            self.consumer.close()
            self.logger.info("✓ Consumer closed")

if __name__ == '__main__':
    kafka = KafkaConnection()
    kafka.connect()
