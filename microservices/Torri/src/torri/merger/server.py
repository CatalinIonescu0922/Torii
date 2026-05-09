import os
import json
import signal
import threading
from typing import Dict, Any, Optional
from confluent_kafka import Consumer, KafkaError, TopicPartition
from shared.logger_setup import get_logger
from shared.merger_models import MergeRequest, MergeResponse, MergeStatus, MergeAction
from pydantic import ValidationError

from torri.kafka.producer import KafkaProducerClient
from torri.merger.merger import Merger, SpeculativeMergeItem, MergerTreeError, GitCommandError
import subprocess

class KafkaConsumerWorker:
    """
    The main Worker Daemon Server holding the Kafka polling loop and coordinating jobs.
    """
    def __init__(self):
        self.logger = get_logger("torri.merger.server")
        
        # Init internal Kafka Producer to send responses out
        self.producer = KafkaProducerClient(os.getenv("KAFKA_SERVER", "localhost:9094"))
        self.input_topic = os.getenv("KAFKA_MERGER_INPUT_TOPIC", "merger-requests")
        self.output_topic = os.getenv("KAFKA_MERGER_OUTPUT_TOPIC", "merger-responses")
        self.dlq_topic = os.getenv("KAFKA_MERGER_DLQ_TOPIC", "merger-dlq")
        
        self.workspace_root = os.getenv("MERGER_WORKSPACE_PATH", "/tmp/torri_merger_workspaces")
        self.cache_root = os.path.join(self.workspace_root, "cache")  # Persistent cache for repos
        os.makedirs(self.workspace_root, exist_ok=True)
        os.makedirs(self.cache_root, exist_ok=True)

        # Default orchestrator uses cache (no cleanup after job)
        self.cache_orchestrator = Merger(self.cache_root)
        
        self.consumer_config = {
            'bootstrap.servers': os.getenv("KAFKA_SERVER", "localhost:9094"),
            'group.id': os.getenv("KAFKA_MERGER_GROUPID", "merger-workers-group"),
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,  # Requires manual commit for At-Least-Once resiliency
            'max.poll.interval.ms': 600000  # Long Git fetches allowed (10 mins)
        }
        self.consumer = Consumer(self.consumer_config)
        self.running = False
        
        # Setup OS Signals for clean administrative shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        self.logger.info("Received termination signal %s. Shutting down gracefully...", signum)
        self.running = False

    def run(self):
        """Starts the consumer daemon loop."""
        self.logger.info("Subscribing to topic: %s", self.input_topic)
        self.consumer.subscribe([self.input_topic])
        self.running = True
        
        try:
            while self.running:
                # Polling block
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    self.logger.error("Consumer error: %s", msg.error())
                    continue
                
                # We have a valid message to process
                self._handle_message(msg)
                
        except Exception as e:
            self.logger.error("Fatal worker exception: %s", e, exc_info=True)
        finally:
            self.shutdown()

    def _handle_message(self, msg):
        """Parses and delegates the payload to the domain logic."""
        response_payload = {}
        merged_hash = None
        status = MergeStatus.SUCCESS
        error_msg = None
        
        # 1. Parse JSON -> Pydantic Model
        try:
            raw_data = json.loads(msg.value().decode('utf-8'))
            request = MergeRequest(**raw_data)
        except (ValidationError, json.JSONDecodeError, TypeError) as e:
            self.logger.error("Failed to parse MergeRequest: %s", e)
            self._send_to_dlq(msg.value())
            self.consumer.commit(msg)
            return
        
        # Annotate logger dynamically!
        # Contextual tracing is crucial as detailed in the architecture plan
        job_logger = get_logger("torri.merger.job")
        job_logger.info("Processing action %s for repo %s (Job: %s, Trace: %s)", request.action, request.target_repository, request.job_id, request.trace_id)
        
        # 2. Synchronous Thread Domain Execution Orchestrated
        try:
            repo_name = request.target_repository.split("/")[-1].replace(".git", "")
            
            # Use persistent cache orchestrator - repos are kept for reuse
            # This avoids re-cloning on every job, which is efficient for burst traffic
            
            if request.action == MergeAction.SPECULATIVE_MERGE:
                # Build speculative namespace - preserving exact order from patchset_refs
                items = [
                    SpeculativeMergeItem(
                        target_repo_url=request.target_repository,
                        repo_name=repo_name,
                        base_branch=request.base_branch,
                        patchset_ref=ref,
                        strategy=request.strategy or "merge",
                        index=idx  # Track original position in patchset_refs list
                    )
                    for idx, ref in enumerate(request.patchset_refs)
                ]
                
                # DEBUG: Log the items as received from Kafka
                job_logger.info("📮 Received from Kafka - patchset_refs order: %s", request.patchset_refs)
                job_logger.info("📮 Created items with indices: %s", [(item.patchset_ref, item.index) for item in items])
                
                # Orchestrate: this handles state hygiene, GC protection, and Checkpoint rollbacks safely
                # Uses cache orchestrator which keeps repos for reuse across jobs
                merger_results = self.cache_orchestrator.mergeChanges(items)
                
                # Extract the newly tagged namespace (refs/torri/...)
                merged_hash = merger_results.get(repo_name)
                
            elif request.action == MergeAction.READ_CONFIG:
                if request.files_to_read and request.patchset_refs:
                    # Leverage the internal mapped _get_repo so it inherently tests against Tree Collisions
                    repo = self.cache_orchestrator._get_repo(request.target_repository, repo_name)
                    files_content = repo.read_files_at_ref(request.patchset_refs[0], request.files_to_read)
                    response_payload = files_content

        except subprocess.TimeoutExpired as e:
            status = MergeStatus.TIMEOUT
            error_msg = "Git operation timed out"
            job_logger.error(error_msg)
        except GitCommandError as e:
            status = MergeStatus.MERGE_CONFLICT  # Inferred failure mostly as conflict or bad ref
            error_msg = str(e)
            job_logger.error("Git Conflict/Failure: %s", error_msg)
        except Exception as e:
            status = MergeStatus.ERROR
            error_msg = str(e)
            job_logger.error("Unexpected worker error: %s", error_msg, exc_info=True)

        # 3. Formulate the strictly typed Response
        response = MergeResponse(
            job_id=request.job_id,
            status=status,
            merged_commit_hash=merged_hash,
            payload=response_payload,
            error_message=error_msg
        )
        
        # 4. Produce to Response Topic
        repo_key = request.target_repository.split("/")[-1]
        self.producer.send_message(
            self.output_topic, 
            key=repo_key, 
            value=response.model_dump(exclude_none=True)
        )
        
        job_logger.info("Finished task. Status: %s. Emitted to %s", status, self.output_topic)

        # 5. Commit Offset ONLY AFTER PRODUCING RESPONSE (Guarantees At-Least-Once Delivery)
        self.consumer.commit(msg)

    def _send_to_dlq(self, raw_value: bytes):
        """Sends corrupted messages to a Dead Letter Queue"""
        try:
            self.logger.warning("Routing unparseable message to DLQ: %s", self.dlq_topic)
            self.producer.send_message(self.dlq_topic, key="dlq_message", value=raw_value.decode('utf-8'))
        except Exception as dlq_err:
            self.logger.error("Failed to write to DLQ: %s", dlq_err)

    def shutdown(self):
        """Clean resource de-allocation."""
        self.logger.info("Closing Kafka Consumer and flushing Producer...")
        self.running = False
        try:
            self.consumer.close()
        except:
            pass
        self.producer.flush()
        self.logger.info("Shutdown complete.")

if __name__ == "__main__":
    worker = KafkaConsumerWorker()
    worker.run()
