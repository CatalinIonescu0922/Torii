"""
Scheduler queue for managing event processing and pipeline dispatch.
Threading-based component that receives enriched events from GerritEventProcessor.
"""

import threading
import queue
import yaml
import os
from typing import Optional, Dict, List

from shared.logger_setup import get_logger
from shared.gerritmodel import GerritTriggerEvent
from torri.scheduler.redis_client import TorriRedis
from torri.scheduler.pipeline_config import PipelineConfigLoader, PipelineConfig
from torri.scheduler.pipeline_manager import (
    BasePipelineManager, CheckPipeline, GatePipeline,
    ChangeInfoModel, ChangeState
)
from torri.scheduler.job_runner import launch_jobs
from torri.scheduler.status_writer import refresh_status


class SchedulerQueue(threading.Thread):
    """Main scheduler thread that processes events and routes to pipelines."""

    def __init__(self, gerrit_conn, source, yaml_dir: str, redis_url: Optional[str] = None):
        super().__init__(daemon=True, name="SchedulerQueue")
        self.logger = get_logger("torri.scheduler.queue")

        self.gerrit_conn = gerrit_conn
        self.source = source
        self.yaml_dir = yaml_dir
        self.redis = TorriRedis(redis_url)

        self.event_queue: queue.Queue = queue.Queue()
        self.running = False
        self.pipelines: Dict[str, BasePipelineManager] = {}
        self.pipeline_configs: Dict[str, PipelineConfig] = {}
        # project_name -> list of pipeline names the project participates in
        self.project_pipelines: Dict[str, List[str]] = {}
        # (project_name, pipeline_name) -> list of job names
        self.project_pipeline_jobs: Dict[tuple, List[str]] = {}

        self.logger.info("SchedulerQueue initialized")
    
    def addEvent(self, event: GerritTriggerEvent):
        """Called by GerritEventProcessor to queue an event for processing."""
        try:
            self.event_queue.put(event, timeout=5)
            self.logger.debug("Queued event for change %s", event.change_number)
        except queue.Full:
            self.logger.error("Event queue full, dropping event for change %s", event.change_number)
    
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
        """Load pipeline configs and project->pipeline mappings from YAML files."""
        try:
            pipelines_path = os.path.join(self.yaml_dir, 'pipelines.yaml')
            loader = PipelineConfigLoader(pipelines_path)
            self.pipeline_configs = loader.get_all_pipelines()

            for name, pipeline_config in self.pipeline_configs.items():
                if pipeline_config.manager == 'dependent':
                    self.pipelines[name] = GatePipeline(name, self.redis, self.gerrit_conn)
                else:
                    self.pipelines[name] = CheckPipeline(name, self.redis)
                self.logger.info("Initialized pipeline %s (manager=%s)", name, pipeline_config.manager)

            projects_path = os.path.join(self.yaml_dir, 'projects.yaml')
            with open(projects_path, 'r') as f:
                projects_data = yaml.safe_load(f) or {}

            for item in projects_data.get('projects', []):
                project = item.get('project', {})
                project_name = project.get('name')
                if not project_name:
                    continue
                # A project participates in a pipeline if the pipeline name is a key in the project
                pipelines_for_project = [p for p in self.pipeline_configs if p in project]
                self.project_pipelines[project_name] = pipelines_for_project
                for pipeline_name in pipelines_for_project:
                    jobs = project.get(pipeline_name, {}).get('jobs', [])
                    self.project_pipeline_jobs[(project_name, pipeline_name)] = jobs
                self.logger.info("Project %s -> pipelines %s", project_name, pipelines_for_project)

        except Exception as e:
            self.logger.error("Error initializing pipelines: %s", e, exc_info=True)
    
    def _process_event(self, event: GerritTriggerEvent):
        """Process enriched event from GerritEventProcessor."""
        try:
            change_id = event.change_number
            project_name = event.project_name
            branch = event.branch

            if not change_id or not project_name:
                self.logger.debug(
                    "Event type=%s has no change_number or project_name, skipping",
                    event.type,
                )
                return

            self.logger.info(
                "Processing event type=%s change=%s project=%s",
                event.type, change_id, project_name,
            )

            pipeline_names = self.project_pipelines.get(project_name)
            if not pipeline_names:
                self.logger.info(
                    "No pipelines configured for project %s, skipping", project_name
                )
                return

            change_info = ChangeInfoModel(change_id, project_name, branch)
            change_info.state = ChangeState.QUEUED

            for pipeline_name in pipeline_names:
                pipeline = self.pipelines.get(pipeline_name)
                pipeline_config = self.pipeline_configs.get(pipeline_name)
                if not pipeline or not pipeline_config:
                    self.logger.warning("Pipeline %s not found", pipeline_name)
                    continue

                if not self._change_meets_requirements(event, pipeline_config):
                    continue

                if isinstance(pipeline, GatePipeline):
                    queue_pos = pipeline.enqueue_change(change_id, project_name, branch)
                else:
                    queue_pos = pipeline.enqueue_change(change_id)

                pipeline.save_change_state(change_info)
                self.logger.info(
                    "Enqueued change %s to pipeline %s at position %d",
                    change_id, pipeline_name, queue_pos,
                )

                # Tell Gerrit the pipeline has started
                if pipeline_config.start_message and event.patch_number:
                    self.gerrit_conn.set_review(
                        change_id, event.patch_number,
                        message=pipeline_config.start_message,
                    )

                job_names = self.project_pipeline_jobs.get((project_name, pipeline_name), [])
                refresh_status(self.redis, list(self.pipeline_configs.keys()), self.gerrit_conn)

                # Capture loop variables for the closure
                captured_pipeline_config = pipeline_config
                captured_patchset = event.patch_number

                def on_done(succeeded, _pc=captured_pipeline_config, _ps=captured_patchset):
                    labels = _pc.success_labels if succeeded else _pc.failure_labels
                    message = (
                        f"{_pc.name} pipeline {'succeeded' if succeeded else 'failed'}"
                    )
                    if _ps and labels:
                        self.gerrit_conn.set_review(
                            change_id, _ps, message=message, labels=labels
                        )
                    elif _ps:
                        self.gerrit_conn.set_review(change_id, _ps, message=message)
                    refresh_status(
                        self.redis, list(self.pipeline_configs.keys()), self.gerrit_conn
                    )

                launch_jobs(change_id, pipeline_name, job_names, self.redis, on_done)

        except Exception as e:
            self.logger.error("Error processing event: %s", e, exc_info=True)

    def _change_meets_requirements(self, event: GerritTriggerEvent, pipeline_config: PipelineConfig) -> bool:
        """Check open/current-patchset/label requirements against the cached change."""
        change = self.source.getChange(event.change_number, event.patch_number)

        if pipeline_config.require_open:
            if change is None or change.status != "NEW":
                self.logger.info(
                    "Change %s rejected from pipeline %s: not open (status=%s)",
                    event.change_number, pipeline_config.name,
                    change.status if change else "unknown",
                )
                return False

        if pipeline_config.require_current_patchset:
            if change is None or event.patch_number != str(change.patchset):
                self.logger.info(
                    "Change %s rejected from pipeline %s: not current patchset (event=%s latest=%s)",
                    event.change_number, pipeline_config.name,
                    event.patch_number, change.patchset if change else "unknown",
                )
                return False

        if change is None:
            return False

        # Check required labels — each must meet or exceed the required value
        for label_name, required_value in pipeline_config.required_approvals.items():
            current_value = change.labels.get(label_name, 0)
            if current_value < required_value:
                self.logger.info(
                    "Change %s rejected from pipeline %s: %s is %d, need %d",
                    event.change_number, pipeline_config.name,
                    label_name, current_value, required_value,
                )
                return False

        # Check reject labels — if any match, block the change
        for label_name, reject_value in pipeline_config.reject_approvals.items():
            current_value = change.labels.get(label_name, 0)
            blocked = (
                current_value in reject_value
                if isinstance(reject_value, list)
                else current_value == reject_value
            )
            if blocked:
                self.logger.info(
                    "Change %s rejected from pipeline %s: %s=%d matches reject rule",
                    event.change_number, pipeline_config.name,
                    label_name, current_value,
                )
                return False

        return True
    

