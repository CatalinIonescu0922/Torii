from shared.logger_setup import get_logger


class GerritSource:

    name = "gerrit"

    def __init__(self, connection=None):
        self.logger = get_logger("torri.source.gerrit")
        self.connection = connection

    def getRefSha(self, change):
        return None

    def isMerged(self, change, head=None):
        return None

    def canMerge(self, change, allow_needs):
        return None

    def getChange(self, event, project=None, refresh=False):
        if getattr(event, "change_number", None) and self.connection:
            return self.connection.getChange(event.change_number)
        return None

    def getProjectOpenChanges(self, project):
        return None

    def getGitUrl(self, project):
        return None