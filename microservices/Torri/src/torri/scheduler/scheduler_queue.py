"""
Scheduler queue for managing event processing and pipeline dispatch.
Threading-based component that receives enriched events from GerritEventProcessor.
"""

import threading
import queue
from typing import Optional, Dict, Any
from datetime import datetime

from shared.logger_setup import get_logger
from shared.gerritmodel import GerritTriggerEvent, GerritChange
from torri.scheduler.redis_client import TorriRedis
from torri.scheduler.config_loader import ConfigurationLoader
from torri.scheduler.approval_verifier import ApprovalVerifier
from torri.scheduler.message_template import MessageTemplate
from torri.scheduler.pipeline_manager import (
    BasePipelineManager, CheckPipeline, GatePipeline, ReportPipeline,
    ChangeInfoModel, ChangeState
)


class SchedulerQueue(threading.Thread):
    """Main scheduler thread that processes events and routes to pipelines."""
    
    def __init__(self, gerrit_conn, redis_url: Optional[str] = None):
        super().__init__(daemon=True, name="SchedulerQueue")
        self.logger = get_logger("torri.scheduler.queue")
        
        self.gerrit_conn = gerrit_conn
        self.redis = TorriRedis(redis_url)
        self.config = ConfigurationLoader()
        self.approval_verifier = ApprovalVerifier(gerrit_conn, self.config)
        self.message_template = MessageTemplate(self.config)
        
        self.event_queue: queue.Queue = queue.Queue()
        self.running = False
        self.pipelines: Dict[str, BasePipelineManager] = {}
        
        self.logger.info("SchedulerQueue initialized")
    
    def addEvent(self, event: GerritTriggerEvent):
        """Called by GerritEventProcessor to queue an event for processing."""
        try:
            self.event_queue.put(event, timeout=5)
            self.logger.debug("Queued event for change %s", event.change.number)
        except queue.Full:
            self.logger.error("Event queue full, dropping event for change %s", event.change.number)
    
    def run(self):
        """Main event processing loop."""
        self.running = True
        self.logger.info("Scheduler queue thread started")
        
        try:
            self._initialize_pipelines()
            
            while self.running:
                try:
                    event = self.event_queue.get(timeout=1)
                    self._process_event(event)
                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.error("Error in event processing loop: %s", e, exc_info=True)
        
        finally:
            self.running = False
            self.logger.info("Scheduler queue thread stopped")
    
    def stop(self):
        """Stop the scheduler thread gracefully."""
        self.running = False
    
    def _initialize_pipelines(self):
        """Initialize pipeline managers from config."""
        try:
            config = self.config.load_all()
            
            for pipeline_id, pipeline_config in config.get('pipelines', {}).items():
                pipeline_type = pipeline_config.get('type', 'check')
                
                if pipeline_type.lower() == 'check':
                    self.pipelines[pipeline_id] = CheckPipeline(pipeline_id, self.redis)
                elif pipeline_type.lower() == 'gate':
                    self.pipelines[pipeline_id] = GatePipeline(pipeline_id, self.redis, self.gerrit_conn)
                elif pipeline_type.lower() == 'report':
                    self.pipelines[pipeline_id] = ReportPipeline(pipeline_id, self.redis)
                
                self.logger.info("Initialized %s pipeline: %s", pipeline_type, pipeline_id)
        
        except Exception as e:
            self.logger.error("Error initializing pipelines: %s", e, exc_info=True)
    
    def _process_event(self, event: GerritTriggerEvent):
        """Process enriched event from GerritEventProcessor."""
        try:
            change = event.change
            change_id = str(change.number)
            project_name = change.project
            
            self.logger.info(
                "Processing event for change %s on project %s",
                change_id, project_name
            )
            
            config = self.config.load_all()
            project_config = config.get('projects', {}).get(project_name)
            
            if not project_config:
                self.logger.warning("Project config not found for %s", project_name)
                return
            
            is_approved, reason = self.approval_verifier.verify_project_approval(
                change_id, project_name
            )
            
            if not is_approved:
                self.logger.info("Change %s not approved: %s", change_id, reason)
                self._post_message(change_id, f"Not ready: {reason}")
                return
            
            pipelines_to_enqueue = project_config.get('pipelines', [])
            
            change_info = ChangeInfoModel(
                change_id,
                project_name,
                change.branch
            )
            change_info.state = ChangeState.QUEUED
            
            for pipeline_id in pipelines_to_enqueue:
                if pipeline_id not in self.pipelines:
                    self.logger.warning("Pipeline not found: %s", pipeline_id)
                    continue
                
                pipeline = self.pipelines[pipeline_id]
                
                is_approved, reason = self.approval_verifier.verify_pipeline_approval(
                    change_id, pipeline_id
                )
                
                if not is_approved:
                    self.logger.info(
                        "Change %s not approved for pipeline %s: %s",
                        change_id, pipeline_id, reason
                    )
                    continue
                
                # For gate pipeline, pass additional context for algorithm
                if isinstance(pipeline, GatePipeline):
                    queue_pos = pipeline.enqueue_change(change_id, project_name, change.branch)
                else:
                    queue_pos = pipeline.enqueue_change(change_id)
                
                self.logger.info(
                    "Enqueued change %s to pipeline %s at position %d",
                    change_id, pipeline_id, queue_pos
                )
            
            pipeline.save_change_state(change_info)
            self.logger.info("Change %s queued successfully", change_id)
        
        except Exception as e:
            self.logger.error("Error processing event: %s", e, exc_info=True)
    
    def _post_message(self, change_id: str, message: str):
        """Post message to change in Gerrit."""
        try:
            self.logger.debug("Posting message to change %s: %s", change_id, message)
        except Exception as e:
            self.logger.error("Error posting message: %s", e, exc_info=True)
