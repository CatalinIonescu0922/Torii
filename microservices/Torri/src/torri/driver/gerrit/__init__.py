from torri.driver import Driver
from torri.gerrit.gerritconnection import GerritRestConnection
from torri.gerrit.gerritsource import GerritSource
from torri.driver.gerrit.gerritreporter import GerritReporter
from torri.trigger.gerrittrigger import GerritTrigger


class GerritDriver(Driver):
    """
    Gerrit driver. Owns the connection, source, trigger, and reporter for Gerrit.

    Pass existing connection/source when they were already constructed elsewhere
    (e.g. cmd/scheduler.py), otherwise the driver creates its own.
    """

    def __init__(self, connection=None, source=None, connection_config=None, redis=None):
        connection_config = connection_config or {}
        if connection is not None:
            self.connection = connection
        else:
            self.connection = GerritRestConnection(
                connection_config.get('base_url'),
                auth=connection_config.get('auth'),
                redis=redis,
            )
        self.source = source if source is not None else GerritSource(self.connection, redis, self)
        self.reporter = GerritReporter(self, self.connection)

    @property
    def name(self) -> str:
        return 'gerrit'

    def getConnection(self):
        return self.connection

    def getSource(self):
        return self.source

    def getTrigger(self):
        return GerritTrigger(self, self.connection)

    def getReporter(self):
        return self.reporter
