from abc import ABC, abstractmethod
from torri.driver import SourceInterface

class BaseSource(SourceInterface):
    """
    Base Source. The canonical provider of SCM truth.
    Does not hold network state, uses connection to fetch data.
    """
    def __init__(self, driver, connection):
        self.driver = driver
        self.connection = connection

    @abstractmethod
    def getRefSha(self, project, ref):
        pass

    @abstractmethod
    def isMerged(self, change, head=None):
        pass

    @abstractmethod
    def canMerge(self, change, allow_needs=True):
        pass

    @abstractmethod
    def getChange(self, event, refresh=False):
        pass
