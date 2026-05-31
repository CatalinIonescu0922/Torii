from torri.reporter import BaseReporter
from torri.model import BaseReporterAction
from shared.logger_setup import get_logger


class GerritReporterAction(BaseReporterAction):
    """
    A baked-in reporter action for Gerrit.
    Stores labels and message at config load time so the scheduler
    only calls report(change_id, patchset) without knowing Gerrit details.
    """

    def __init__(self, reporter, labels: dict, message: str):
        self.reporter = reporter
        self.labels = labels
        self.message = message

    def report(self, change_id: str, patchset: str) -> None:
        self.reporter.report(change_id, patchset, self.message, self.labels)


class GerritReporter(BaseReporter):
    name = 'gerrit'

    def __init__(self, driver, connection, config=None):
        super().__init__(driver, connection, config)
        self.logger = get_logger("torri.reporter.gerrit")

    def report(self, change_id: str, patchset: str, message: str, labels: dict = None) -> None:
        self.logger.info("Reporting to Gerrit change %s patchset %s", change_id, patchset)
        self.connection.set_review(change_id, patchset, message, labels)

    def buildAction(self, label_list: list, message: str) -> GerritReporterAction:
        """
        Build a GerritReporterAction from the YAML label list.

        label_list comes from pipelines.yaml, e.g. [{'Verified': 1}].
        Merges all single-key dicts into one labels dict.
        """
        labels = {}
        for item in label_list:
            if isinstance(item, dict):
                labels.update(item)
        return GerritReporterAction(self, labels, message)