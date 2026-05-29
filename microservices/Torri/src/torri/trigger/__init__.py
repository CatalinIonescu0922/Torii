from abc import ABC, abstractmethod
from torri.driver import TriggerInterface

class BaseTrigger(TriggerInterface):
    """
    Determines which events from the Connection should start a job.
    """
    def __init__(self, driver, connection, config):
        self.driver = driver
        self.connection = connection
        self.config = config

    @abstractmethod
    def getEventFilters(self):
        pass
