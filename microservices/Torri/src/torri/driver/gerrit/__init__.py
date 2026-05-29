from torri.driver import Driver
from torri.gerrit.gerritconnection import GerritRestConnection
from torri.gerrit.gerritsource import GerritSource
from torri.driver.gerrit.gerritreporter import GerritReporter

class GerritDriver(Driver):
    """
    Glue driver for Gerrit.
    """
    
    def __init__(self, connection_config=None, redis=None):
        self.connection_config = connection_config or {}
        self.redis = redis
        # Centralizing the instantiation here:
        self.connection = GerritRestConnection(
            self.connection_config.get('base_url'),
            auth=self.connection_config.get('auth'),
            redis=self.redis
        )
        # Source needs driver and connection
        self.source = GerritSource(self.connection, self.redis, self)
        # Reporter needs driver and connection
        self.reporter = GerritReporter(self, self.connection)

    @property
    def name(self) -> str:
        return 'gerrit'

    def getConnection(self):
        return self.connection

    def getSource(self):
        return self.source

    def getTrigger(self):
        # We can implement a formal trigger later, for now we just return None
        return None

    def getReporter(self):
        return self.reporter
