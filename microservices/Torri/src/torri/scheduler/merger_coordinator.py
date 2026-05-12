"""
Coordination with Merger service via Kafka.

Responsibilities:
- Send MergeRequest to Merger service (generate synthetic refs)
- Wait for MergeResponse (synthetic ref ready)
- Handle merge failures and fallback logic
"""

import json
import time
from typing import Optional, Tuple
from shared.logger_setup import get_logger
from shared.merger_models import MergeRequest, MergeAction


class MergerCoordinator:
    """Coordinates with Merger service to generate synthetic refs for testing."""
    
    def __init__(self, kafka_producer, kafka_consumer, redis_client):
        """
        Args:
            kafka_producer: KafkaProducerClient for sending MergeRequests
            kafka_consumer: Kafka consumer for reading MergeResponses
            redis_client: TorriRedis for caching merge results
        """
        self.logger = get_logger("torri.scheduler.merger_coordinator")
        self.producer = kafka_producer
        self.consumer = kafka_consumer
        self.redis = redis_client
        
        self.merge_request_topic = "merger-requests"
        self.merge_response_topic = "merger-responses"
    
    def request_synthetic_ref(
        self,
        job_id: str,
        target_repo: str,
        base_branch: str,
        patchset_refs: list,
        strategy: str = "merge"
    ) -> Tuple[bool, Optional[str]]:
        """
        Request Merger service to generate a synthetic ref.
        
        Workflow:
        1. Create MergeRequest with all dependent changes
        2. Send to Kafka "merger-requests" topic
        3. Wait for response on "merger-responses" topic
        4. Cache result in Redis
        
        Args:
            job_id: Unique job identifier
            target_repo: Repository URL (e.g., "gerrit:repo.git")
            base_branch: Base branch (e.g., "master")
            patchset_refs: List of patchset refs to merge
            strategy: Merge strategy (merge, rebase, cherry-pick)
        
        Returns:
            (success, synthetic_ref_hash)
            - success: True if merger succeeded
            - synthetic_ref_hash: e.g., "refs/torri/abc123def456"
        """
        try:
            # Create merge request
            merge_request = MergeRequest(
                job_id=job_id,
                target_repository=target_repo,
                base_branch=base_branch,
                patchset_refs=patchset_refs,
                action=MergeAction.SPECULATIVE_MERGE,
                strategy=strategy
            )
            
            self.logger.info(
                "Requesting synthetic ref for job=%s refs=%s",
                job_id, patchset_refs
            )
            
            # Check cache first (in case already processed)
            cached_result = self._get_cached_merge_result(job_id)
            if cached_result:
                self.logger.debug("Cache hit for job=%s result=%s", job_id, cached_result)
                return True, cached_result
            
            # Send to Merger service
            self.producer.send_message(
                self.merge_request_topic,
                key=job_id,
                value=merge_request.model_dump(exclude_none=True)
            )
            self.producer.flush()
            
            self.logger.info("Sent MergeRequest to Kafka for job=%s", job_id)
            
            # Wait for response (with timeout)
            synthetic_ref, error = self._wait_for_merge_response(job_id, timeout_seconds=300)
            
            if synthetic_ref:
                # Cache successful result
                self._cache_merge_result(job_id, synthetic_ref)
                self.logger.info(
                    "Received synthetic ref for job=%s ref=%s",
                    job_id, synthetic_ref
                )
                return True, synthetic_ref
            else:
                self.logger.error(
                    "Merger failed for job=%s error=%s",
                    job_id, error
                )
                return False, error
        
        except Exception as e:
            self.logger.error("Error requesting synthetic ref: %s", e)
            return False, str(e)
    
    def _wait_for_merge_response(
        self,
        job_id: str,
        timeout_seconds: int = 300
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Wait for Merger to respond with synthetic ref.
        
        Polls the merger-responses Kafka topic with timeout.
        """
        start_time = time.time()
        poll_interval = 1.0  # Check every 1 second
        
        while time.time() - start_time < timeout_seconds:
            try:
                # Poll Kafka for response
                msg = self.consumer.poll(timeout=1.0)
                
                if msg is None:
                    continue
                
                if msg.error():
                    self.logger.debug("Consumer error: %s", msg.error())
                    continue
                
                # Parse response
                response_data = json.loads(msg.value().decode('utf-8'))
                response_job_id = response_data.get('job_id')
                
                if response_job_id == job_id:
                    # Found our response
                    status = response_data.get('status')
                    merged_hash = response_data.get('merged_commit_hash')
                    error_msg = response_data.get('error_message')
                    
                    self.logger.info(
                        "Got response for job=%s status=%s hash=%s",
                        job_id, status, merged_hash[:8] if merged_hash else None
                    )
                    
                    if status == 'success' and merged_hash:
                        # Create synthetic ref name
                        synthetic_ref = f"refs/torri/job-{job_id}_{merged_hash[:12]}"
                        return synthetic_ref, None
                    else:
                        return None, error_msg or "Merge failed"
                
                # Not our response, continue polling
                self.consumer.commit(msg)
            
            except Exception as e:
                self.logger.warning("Error polling for response: %s", e)
                time.sleep(poll_interval)
        
        return None, f"No response after {timeout_seconds}s"
    
    def _cache_merge_result(self, job_id: str, synthetic_ref: str):
        """Store merge result in Redis for future reference."""
        try:
            cache_key = f"torri:merger:job:{job_id}:result"
            self.redis.set_state(cache_key, {
                'job_id': job_id,
                'synthetic_ref': synthetic_ref,
                'timestamp': time.time(),
            })
        except Exception as e:
            self.logger.warning("Failed to cache merge result: %s", e)
    
    def _get_cached_merge_result(self, job_id: str) -> Optional[str]:
        """Retrieve cached merge result if available."""
        try:
            cache_key = f"torri:merger:job:{job_id}:result"
            cached = self.redis.get_state(cache_key)
            if cached:
                return cached.get('synthetic_ref')
        except Exception as e:
            self.logger.debug("Failed to retrieve cached result: %s", e)
        return None
