from abc import ABC, abstractmethod
from torri.driver import ReporterInterface

class BaseReporter(ReporterInterface):
    """
    Defines how to post feedback (leave comment or votes).
    """
    def __init__(self, driver, connection, config):
        self.driver = driver
        self.connection = connection
        self.config = config

    @abstractmethod
    def report(self, item):
        pass
