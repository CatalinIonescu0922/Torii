from torri.source import BaseSource
from shared.logger_setup import get_logger

class GerritSource(BaseSource):
    """
    Separation layer between the scheduler and the Gerrit connection.
    """
    name = "gerrit"

    def __init__(self, connection=None, redis=None, driver=None):
        super().__init__(driver, connection)
        self.logger = get_logger("torri.source.gerrit")
        self.redis = redis

    def getChange(self, change_number, patchset=None, refresh=False):
        if not refresh and self.redis:
            change = self.redis.get_change(change_number, patchset)
            if change:
                self.logger.debug(
                    "Source Redis hit change=%s patchset=%s labels=%s",
                    change_number, patchset, change.labels,
                )
                return change

        if self.connection:
            self.logger.debug("Source Redis miss, fetching change=%s patchset=%s via connection", change_number, patchset)
            return self.connection.getChange(change_number, patchset)

        return None

    def getRefSha(self, project, ref):
        pass

    def isMerged(self, change, head=None):
        if change.status == 'MERGED':
            return True
        return False

    def canMerge(self, event, pipeline_config):
        """
        Check open/current-patchset/label requirements against the cached change.
        Returns (True, "") if the change qualifies.
        Returns (False, reason) if it does not.
        """
        change = self.getChange(event.change_number, event.patch_number)
        self.logger.debug(
            "Requirements check change=%s pipeline=%s labels=%s status=%s patchset=%s",
            event.change_number, pipeline_config.name,
            change.labels if change else None,
            change.status if change else None,
            change.patchset if change else None,
        )

        if pipeline_config.require_open:
            if change is None or change.status != "NEW":
                status = change.status if change else "unknown"
                return False, f"Change is not open (status: {status})"

        if pipeline_config.require_current_patchset:
            if change is None or event.patch_number != str(change.patchset):
                latest = change.patchset if change else "unknown"
                return False, f"Patchset {event.patch_number} is not the current patchset (latest: {latest})"

        if change is None:
            return False, "Change not found"

        for label_name, required_value in pipeline_config.required_approvals.items():
            current_value = change.labels.get(label_name, 0)
            if current_value < required_value:
                return False, f"Missing required vote: {label_name} is {current_value:+d}, need {required_value:+d}"

        for label_name, reject_value in pipeline_config.reject_approvals.items():
            current_value = change.labels.get(label_name, 0)
            blocked = (current_value in reject_value if isinstance(reject_value, list) else current_value == reject_value)
            if blocked:
                return False, f"Blocked by vote: {label_name}={current_value:+d}"

        return True, ""
