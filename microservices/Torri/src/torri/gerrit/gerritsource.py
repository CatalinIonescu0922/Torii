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
