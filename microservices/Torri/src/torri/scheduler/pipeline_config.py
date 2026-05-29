"""
Pipeline configuration loader.

Responsibilities:
- Load pipeline definitions from YAML
- Delegate trigger/reporter construction to the appropriate driver
- Produce PipelineConfig objects with typed filter and action lists
"""

import yaml
from typing import Dict, List, Optional, Tuple

from shared.logger_setup import get_logger
from torri.model import BaseEventFilter, BaseReporterAction


class PipelineConfig:
    """
    Single pipeline configuration, driver-agnostic.

    Triggers and reporter actions are fully resolved objects — the scheduler
    never needs to know they came from Gerrit (or GitHub, GitLab, etc.).
    """

    def __init__(
        self,
        config_dict: dict,
        triggers: List[BaseEventFilter],
        success_actions: List[BaseReporterAction],
        failure_actions: List[BaseReporterAction],
    ):
        self.name = config_dict.get('name')
        self.manager = config_dict.get('manager', 'independent')
        self.start_message = config_dict.get('start-message', f'[Torii] Starting {self.name} pipeline')
        self.success_message = config_dict.get('success-message', f'[Torii] {self.name} pipeline succeeded')
        self.failure_message = config_dict.get('failure-message', f'[Torii] {self.name} pipeline failed')

        # Requirements checked by can_change_enter()
        require_dict = config_dict.get('require', {})
        self.require_open = require_dict.get('open', True)
        self.require_current_patchset = require_dict.get('current-patchset', True)
        self.required_approvals = _parse_approvals(require_dict.get('approval', []))

        reject_dict = config_dict.get('reject', {})
        self.reject_approvals = _parse_approvals(reject_dict.get('approval', []))

        # Driver-backed polymorphic objects
        self.triggers = triggers
        self.success_actions = success_actions
        self.failure_actions = failure_actions

    def can_change_enter(self, change, patchset: str) -> Tuple[bool, str]:
        """
        Decide whether a change is allowed to enter this pipeline.

        change   — the change object fetched from the source
        patchset — the patchset number that triggered the event
        """
        if self.require_open:
            if change is None or change.status != "NEW":
                status = change.status if change else "unknown"
                return False, f"Change is not open (status: {status})"

        if self.require_current_patchset:
            if change is None or str(patchset) != str(change.patchset):
                latest = change.patchset if change else "unknown"
                return False, f"Patchset {patchset} is not current (latest: {latest})"

        if change is None:
            return False, "Change not found"

        for label, required in self.required_approvals.items():
            current = change.labels.get(label, 0)
            if current < required:
                return False, f"Missing required vote: {label} is {current:+d}, need {required:+d}"

        for label, rejected in self.reject_approvals.items():
            current = change.labels.get(label, 0)
            blocked = current in rejected if isinstance(rejected, list) else current == rejected
            if blocked:
                return False, f"Blocked by vote: {label}={current:+d}"

        return True, ""

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'manager': self.manager,
            'start_message': self.start_message,
            'failure_message': self.failure_message,
            'require_open': self.require_open,
            'require_current_patchset': self.require_current_patchset,
            'required_approvals': self.required_approvals,
            'reject_approvals': self.reject_approvals,
        }


def _normalize_label_name(label: str) -> str:
    """code-review → Code-Review, verified → Verified"""
    return '-'.join(part.capitalize() for part in label.split('-'))


def _parse_approvals(approval_list: list) -> Dict[str, int]:
    """Convert [{code-review: 2}] → {'Code-Review': 2}"""
    result = {}
    for item in approval_list:
        if isinstance(item, dict):
            for label, value in item.items():
                result[_normalize_label_name(label)] = value
    return result


class PipelineConfigLoader:
    """
    Loads pipeline configurations from YAML.

    drivers: mapping of driver name → driver instance.
    Each driver provides getTrigger() and getReporter() factories so the loader
    can produce typed filter and action objects without knowing Gerrit internals.
    """

    def __init__(self, yaml_file_path: str, drivers: dict = None):
        self.logger = get_logger("torri.scheduler.pipeline_config")
        self.yaml_file = yaml_file_path
        self.drivers = drivers or {}
        self.pipelines: Dict[str, PipelineConfig] = {}
        self._load()

    def _build_triggers(self, trigger_section: dict) -> List[BaseEventFilter]:
        filters = []
        for driver_name, config_list in trigger_section.items():
            driver = self.drivers.get(driver_name)
            if driver is None:
                self.logger.warning("No driver registered for trigger source '%s'", driver_name)
                continue
            filters.extend(driver.getTrigger().getEventFilters(config_list or []))
        return filters

    def _build_reporter_actions(
        self, reporter_section: dict, message: str
    ) -> List[BaseReporterAction]:
        actions = []
        for driver_name, label_list in reporter_section.items():
            driver = self.drivers.get(driver_name)
            if driver is None:
                self.logger.warning("No driver registered for reporter '%s'", driver_name)
                continue
            actions.append(driver.getReporter().buildAction(label_list or [], message))
        return actions

    def _load(self):
        try:
            with open(self.yaml_file, 'r') as f:
                data = yaml.safe_load(f)

            if not data or 'pipelines' not in data:
                self.logger.warning("No pipelines found in %s", self.yaml_file)
                return

            for pipeline_item in data['pipelines']:
                raw = pipeline_item.get('pipeline')
                if not raw:
                    continue

                pipeline_name = raw.get('name', '<unknown>')
                success_message = raw.get('success-message', f'[Torii] {pipeline_name} pipeline succeeded')
                failure_message = raw.get('failure-message', f'[Torii] {pipeline_name} pipeline failed')

                triggers = self._build_triggers(raw.get('trigger', {}))
                success_actions = self._build_reporter_actions(raw.get('success', {}), success_message)
                failure_actions = self._build_reporter_actions(raw.get('failure', {}), failure_message)

                config = PipelineConfig(raw, triggers, success_actions, failure_actions)
                self.pipelines[config.name] = config
                self.logger.info("Loaded pipeline: %s (manager=%s)", config.name, config.manager)

            self.logger.info("Loaded %d pipelines", len(self.pipelines))

        except Exception as e:
            self.logger.error("Failed to load pipelines from %s: %s", self.yaml_file, e)
            raise

    def get_pipeline(self, pipeline_name: str) -> Optional[PipelineConfig]:
        return self.pipelines.get(pipeline_name)

    def get_all_pipelines(self) -> Dict[str, PipelineConfig]:
        return self.pipelines

