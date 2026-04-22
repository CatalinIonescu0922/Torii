import json
import os
import threading
from typing import Optional
from confluent_kafka import Consumer, KafkaError
from shared.logger_setup import get_logger
from queue import Queue
from typing import Any
class KafkaConnection(threading.Thread):
    """
    Keeps a running connection with Kafka
    reads any incomming messages and sends them to the approapiate structures 
    """
    
    def __init__(self):
        super().__init__(name="KafkaConnection", daemon=True)
        self.logger = get_logger("torri.kafka.connection")
        self.consumer: Optional[Consumer] = None
        self.running = False
        self.event_queue = Queue(0)
        # Consumer configuration
        self.consumer_config = {
            'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:9094"),
            'group.id': os.getenv("KAFKA_GROUPID", "events-consumer-group"),
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,  # Manual commit for reliability
            'max.poll.interval.ms': 300000  # 5 minutes
        }

        self.input_topic = os.getenv("KAFKA_INPUT_TOPIC", "gerrit-stream-events")

    def connect(self):
        """Establish connection to Kafka and start background consumption."""
        if self.running:
            self.logger.warning("Kafka consumer thread is already running")
            return

        try:
            self.consumer = Consumer(self.consumer_config)
            self.consumer.subscribe([self.input_topic])
            self.running = True
            self.logger.info("Connected to Kafka, subscribed to %s", self.input_topic)
            self.start()
        except Exception as e:
            self.logger.error("Failed to connect to Kafka: %s", e, exc_info=True)
            self.running = False
            raise

    def run(self):
        """Thread entrypoint for the Kafka polling loop."""
        try:
            self.get_events()
        finally:
            self._close_consumer()
    
    def get_events(self):
        """
        Main consumption loop with manual commit.
        """
        if not self.consumer:
            raise RuntimeError("Consumer not initialized. Call connect() first.")
        
        self.logger.info("Starting event consumption loop...")
        # creates the queue of events make the queue infinite 
        try:
            while self.running:
                # Poll for messages
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                
                if msg.error():
                    error = msg.error()
                    partition_eof = getattr(KafkaError, "_PARTITION_EOF", None)
                    if error is not None and partition_eof is not None and error.code() == partition_eof:
                        self.logger.debug("Reached end of partition")
                        continue
                    else:
                        self.logger.error("Kafka error: %s", error)
                        continue

                # Deserialize message
                try:
                    payload = msg.value()
                    if payload is None:
                        self.logger.warning("Received empty payload from Kafka")
                        self.consumer.commit()  # Commit to skip bad message
                        continue

                    raw_data = payload.decode('utf-8')
                    event_data = json.loads(raw_data)
                    self.event_queue.put(event_data)
                    self.logger.debug(f"Received data from kafka with this data {event_data}")
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    self.logger.error("Failed to decode message: %s", e)
                    self.consumer.commit()  # Commit to skip bad message
                    continue
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal")

    def get_event_queue(self) -> Queue:
        """Return the shared queue populated by the Kafka polling thread."""
        return self.event_queue
    def getEvent(self, timeout=None) -> dict[str, Any]:
        return self.event_queue.get(timeout=timeout)

    def eventDone(self):
        self.event_queue.task_done()
        self.consumer.commit()
        
    def addEvent(self, data):
        self.event_queue.put(data)

    def _close_consumer(self):
        """Close consumer handle if present."""
        if self.consumer:
            self.consumer.close()
            self.consumer = None
            self.logger.info("✓ Consumer closed")
    
    def shutdown(self, wait: bool = True, timeout: Optional[float] = None):
        """Graceful shutdown for background Kafka polling."""
        self.logger.info("Shutting down Kafka client...")
        self.running = False

        if wait and self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=timeout)
        else:
            self._close_consumer()

if __name__ == '__main__':
    kafka = KafkaConnection()
    kafka.connect()
