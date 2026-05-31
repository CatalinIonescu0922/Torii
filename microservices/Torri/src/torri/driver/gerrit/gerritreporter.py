from torri.reporter import BaseReporter
from shared.logger_setup import get_logger


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