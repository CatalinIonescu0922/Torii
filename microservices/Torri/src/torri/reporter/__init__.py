from abc import ABC, abstractmethod
from torri.driver import ReporterInterface


class BaseReporter(ReporterInterface):
    """
    Defines how to post feedback (leave comment or votes).
    """

    def __init__(self, driver, connection, config=None):
        self.driver = driver
        self.connection = connection
        self.config = config

    @abstractmethod
    def report(self, change_id: str, patchset: str, message: str, labels: dict = None) -> None:
        pass

    def buildAction(self, label_list: list, message: str):
        """
        Create a reporter action from a YAML label list and a message string.
        Subclasses must override this to return their specific action type.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement buildAction")
