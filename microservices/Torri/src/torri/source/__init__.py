from abc import ABC, abstractmethod
from torri.driver import SourceInterface


class BaseSource(SourceInterface):
    """
    Base Source. The canonical provider of SCM truth.
    Fetches and caches change data. Does not own pipeline entry policy.
    """

    def __init__(self, driver, connection):
        self.driver = driver
        self.connection = connection

    @abstractmethod
    def getChange(self, change_number, patchset=None, refresh=False):
        pass

    @abstractmethod
    def getRefSha(self, project, ref):
        pass

    @abstractmethod
    def isMerged(self, change, head=None):
        pass
