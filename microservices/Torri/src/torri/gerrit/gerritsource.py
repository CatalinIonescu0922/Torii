from shared.logger_setup import get_logger


class GerritSource:
    """
    Separation layer between the scheduler and the Gerrit connection.

    The scheduler always calls source.getChange() — never the connection directly.
    Redis is the source of truth. On a miss, the connection fetches from Gerrit
    and populates Redis; subsequent calls are served from Redis.
    """

    name = "gerrit"

    def __init__(self, connection=None, redis=None):
        self.logger = get_logger("torri.source.gerrit")
        self.connection = connection
        self.redis = redis

    def getChange(self, change_number, patchset=None, refresh=False):
        """
        Return a GerritChange for the given change_number and patchset.

        Checks Redis first. On a miss, asks the connection to fetch from Gerrit
        (which also writes the result to Redis), then returns the result.
        """
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

    def getRefSha(self, change):
        return None

    def isMerged(self, change, head=None):
        return None

    def canMerge(self, change, allow_needs):
        return None

    def getProjectOpenChanges(self, project):
        return None

    def getGitUrl(self, project):
        return None