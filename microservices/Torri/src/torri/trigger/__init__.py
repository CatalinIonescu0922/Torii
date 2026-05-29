from abc import ABC, abstractmethod
from typing import List
from torri.driver import TriggerInterface
from torri.model import BaseEventFilter


class BaseTrigger(TriggerInterface):
    """
    Determines which events from the Connection should start a job.
    """

    def __init__(self, driver, connection):
        self.driver = driver
        self.connection = connection

    @abstractmethod
    def getEventFilters(self, config_list: list) -> List[BaseEventFilter]:
        pass
