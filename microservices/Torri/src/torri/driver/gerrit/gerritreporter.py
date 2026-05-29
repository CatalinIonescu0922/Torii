from torri.reporter import BaseReporter
from torri.model import BaseReporterAction
from shared.logger_setup import get_logger


class GerritReporterAction(BaseReporterAction):
    """
    A fully configured Gerrit reporting task.
    Holds everything needed to post one review comment with optional labels.
    """

    def __init__(self, reporter: 'GerritReporter', labels: dict, message: str = ""):
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
        payload = {"message": message}
        if labels:
            payload["labels"] = labels
        endpoint = f"/changes/{change_id}/revisions/{patchset}/review"
        return self.connection._post(endpoint, payload=payload)

    def buildAction(self, label_list: list, message: str) -> GerritReporterAction:
        labels = {}
        for item in label_list:
            if isinstance(item, dict):
                labels.update(item)
        return GerritReporterAction(self, labels, message)
