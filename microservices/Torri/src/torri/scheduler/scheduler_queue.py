"""
Scheduler queue for managing event processing and pipeline dispatch.
Threading-based component that receives enriched events from GerritEventProcessor.
"""

import threading
import queue
import yaml
import os
import re 
from typing import Optional, Dict, List

from shared.logger_setup import get_logger
from shared.gerritmodel import GerritTriggerEvent
from torri.scheduler.redis_client import TorriRedis
from torri.scheduler.pipeline_config import PipelineConfigLoader, PipelineConfig
from torri.scheduler.pipeline_manager import (
    BasePipelineManager, IndependentPipeline, DependentPipeline,
    ChangeInfoModel, ChangeState
)
from torri.scheduler.status_writer import refresh_status
from torri.scheduler.merger_client import request_merge
from torri.scheduler import executor_dispatcher


class SchedulerQueue(threading.Thread):
    """Main scheduler thread that processes events and routes to pipelines."""

    def __init__(
        self,
        gerrit_conn,
        source,
        yaml_dir: str,
        redis_url: Optional[str] = None,
        kafka_bootstrap: str = "kafka:9092",
    ):
        super().__init__(daemon=True, name="SchedulerQueue")
        self.logger = get_logger("torri.scheduler.queue")

        self.gerrit_conn = gerrit_conn
        self.source = source
        self.yaml_dir = yaml_dir
        self.redis = TorriRedis(redis_url)
        self.kafka_bootstrap = kafka_bootstrap
        self.event_queue: queue.Queue = queue.Queue()
        self.running = False
        self.pipelines: Dict[str, BasePipelineManager] = {}
        self.pipeline_configs: Dict[str, PipelineConfig] = {}
        self.project_pipelines: Dict[str, List[str]] = {}
        self.project_pipeline_jobs: Dict[tuple, List[str]] = {}
        # job_name → job config dict (nodeset, timeout, run, pre-run, post-run)
        self.job_configs: Dict[str, dict] = {}
        # nodeset_name → nodeset config dict (name, nodes)
        self.nodeset_configs: Dict[str, dict] = {}

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
        """Load pipeline/project/job/nodeset configs from YAML files."""
        try:
            pipelines_path = os.path.join(self.yaml_dir, 'pipelines.yaml')
            loader = PipelineConfigLoader(pipelines_path)
            self.pipeline_configs = loader.get_all_pipelines()

            for name, pipeline_config in self.pipeline_configs.items():
                if pipeline_config.manager == 'dependent':
                    self.pipelines[name] = DependentPipeline(name, self.redis, source=self.source, gerrit_conn=self.gerrit_conn)
                else:
                    self.pipelines[name] = IndependentPipeline(name, self.redis, source=self.source)
                self.logger.info("Initialized pipeline %s (manager=%s)", name, pipeline_config.manager)

            projects_path = os.path.join(self.yaml_dir, 'projects.yaml')
            with open(projects_path, 'r') as f:
                projects_data = yaml.safe_load(f) or {}

            for item in projects_data.get('projects', []):
                project = item.get('project', {})
                project_name = project.get('name')
                if not project_name:
                    continue
                pipelines_for_project = [p for p in self.pipeline_configs if p in project]
                self.project_pipelines[project_name] = pipelines_for_project
                for pipeline_name in pipelines_for_project:
                    jobs = project.get(pipeline_name, {}).get('jobs', [])
                    self.project_pipeline_jobs[(project_name, pipeline_name)] = jobs
                self.logger.info("Project %s -> pipelines %s", project_name, pipelines_for_project)

            # Load job configs (nodeset, timeout, run playbooks, etc.)
            jobs_path = os.path.join(self.yaml_dir, 'jobs.yaml')
            with open(jobs_path, 'r') as f:
                jobs_data = yaml.safe_load(f) or {}
            for item in jobs_data.get('jobs', []):
                job = item.get('job', {})
                self.job_configs[job['name']] = job

            # Load nodeset configs.
            nodesets_path = os.path.join(self.yaml_dir, 'nodesets.yaml')
            with open(nodesets_path, 'r') as f:
                nodesets_data = yaml.safe_load(f) or {}
            for item in nodesets_data.get('nodesets', []):
                nodeset = item.get('nodeset', {})
                self.nodeset_configs[nodeset['name']] = nodeset

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
                "Processing event type=%s change=%s project=%s connection_name=%s",
                event.type, change_id, project_name, event.event_source
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

                # Skip silently when event type is not listed in this pipeline's triggers.
                trigger_events = [
                    t.get("event")
                    for t in pipeline_config.trigger.get("gerrit", [])
                    if isinstance(t, dict)
                ]
                if trigger_events and event.type not in trigger_events:
                    self.logger.debug(
                        "Event type=%s does not match triggers %s for pipeline %s, skipping",
                        event.type, trigger_events, pipeline_name,
                    )
                    continue
                # verify if the pipeline already runs this change 
                if pipeline.is_change_in_pipeline(change_id):
                    message = f"change {event.change_number} is already running in pipeline {pipeline.pipeline_id}"
                    self.logger.debug(message)
                    self.gerrit_conn.set_review(
                        change_id, event.patch_number , message
                    )
                    continue

                passed, rejection_reason = self._change_meets_requirements(event, pipeline_config)
                if not passed:
                    reject_key = f"torri:rejected:{pipeline_name}:{change_id}:{event.patch_number}"
                    if self.redis.client.setnx(reject_key, rejection_reason):
                        self.redis.client.expire(reject_key, 86400)
                        if event.patch_number:
                            self.gerrit_conn.set_review(
                                change_id, event.patch_number,
                                message=f"[Torii] Not entering {pipeline_name}: {rejection_reason}",
                            )
                    continue

                
                if isinstance(pipeline, DependentPipeline):
                    queue_pos = pipeline.enqueue_change(change_id, project_name, branch)
                else:
                    queue_pos = pipeline.enqueue_change(change_id)

                pipeline.save_change_state(change_info)
                self.logger.info(
                    "Enqueued change %s to pipeline %s at position %d",
                    change_id, pipeline_name, queue_pos,
                )

                # Tell Gerrit the pipeline has started — sent exactly once thanks to start_key guard above
                if pipeline_config.start_message and event.patch_number:
                    self.gerrit_conn.set_review(
                        change_id, event.patch_number,
                        message=pipeline_config.start_message,
                    )

                job_names = self.project_pipeline_jobs.get((project_name, pipeline_name), [])
                refresh_status(self.redis, list(self.pipeline_configs.keys()))

                # Capture loop variables for the closures
                captured_pipeline_config = pipeline_config
                captured_patchset = event.patch_number
                captured_ref = event.ref  # patchset git ref e.g. refs/changes/01/1/1
                captured_is_gate = isinstance(pipeline, DependentPipeline)

                def on_done(
                    status,
                    _pc=captured_pipeline_config,
                    _ps=captured_patchset,
                    _cid=change_id,
                    _pname=pipeline_name,
                    _is_gate=captured_is_gate,
                ):
                    labels = _pc.success_labels if status == "succeeded" else _pc.failure_labels
                    message = _pc.success_message if status == "succeeded" else _pc.failure_message
                    if _ps and labels:
                        self.gerrit_conn.set_review(_cid, _ps, message=message, labels=labels)
                    elif _ps:
                        self.gerrit_conn.set_review(_cid, _ps, message=message)
                    if _is_gate and status == "succeeded":
                        self.logger.info("Gate pipeline succeeded for change %s — submitting to Gerrit", _cid)
                        self.gerrit_conn.submit_change(_cid)
                    # Only remove this change from the queue when the patchset that
                    # started this run is still the one finishing it.  If a new
                    # patchset arrived while we were running, its own on_done handles
                    # its own removal and we must not clobber that.
                    current_change = self.source.getChange(_cid, _ps)
                    if current_change is None or str(current_change.patchset) == str(_ps):
                        self.redis.queue_remove(f"torri:pipeline:{_pname}:queue", _cid)
                    else:
                        self.logger.info(
                            "Patchset %s for change %s is superseded by patchset %s — skipping queue remove",
                            _ps, _cid, current_change.patchset,
                        )
                    refresh_status(self.redis, list(self.pipeline_configs.keys()))

                def on_merge_done(
                    synthetic_ref,
                    error,
                    _jnames=job_names,
                    _on_done=on_done,
                    _cid=change_id,
                    _pname=pipeline_name,
                    _ps=captured_patchset,
                    _project=project_name,
                    _branch=branch,
                ):
                    if error:
                        self.logger.error(
                            "Merge failed for change %s pipeline %s: %s",
                            _cid, _pname, error,
                        )
                        _on_done("failed")
                        return
                    if not synthetic_ref:
                        self.logger.error(
                            "Merger returned no ref for change %s pipeline %s — cannot launch jobs",
                            _cid, _pname,
                        )
                        _on_done("failed")
                        return
                    self.logger.info(
                        "Merge ref ready for change %s pipeline %s: %s — dispatching %d job(s)",
                        _cid, _pname, synthetic_ref, len(_jnames),
                    )
                    executor_dispatcher.dispatch(
                        change_id=_cid,
                        patchset=_ps,
                        pipeline=_pname,
                        project=_project,
                        branch=_branch,
                        job_names=_jnames,
                        job_configs=self.job_configs,
                        nodeset_configs=self.nodeset_configs,
                        synthetic_ref=synthetic_ref,
                        kafka_bootstrap=self.kafka_bootstrap,
                        redis=self.redis,
                        on_done=_on_done,
                    )

                if not captured_ref:
                    self.logger.error(
                        "No patchset ref for change %s patchset %s — cannot request merge",
                        change_id, event.patch_number,
                    )
                    on_done("failed")
                    continue

                merge_job_id = f"{pipeline_name}:{change_id}:{event.patch_number}"
                request_merge(
                    job_id=merge_job_id,
                    project=f"{self.gerrit_conn.base_url}/{project_name}",
                    branch=branch,
                    patchset_refs=[captured_ref],
                    on_done=on_merge_done,
                )

        except Exception as e:
            self.logger.error("Error processing event: %s", e, exc_info=True)

    # def verify_triggers_for_pipeline(trigger_dict : dict , event):
    #     if event.event_source == "gerrit":
            

