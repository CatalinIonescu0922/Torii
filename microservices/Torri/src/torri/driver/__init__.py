from abc import ABC, abstractmethod
from typing import Any, Dict

class ConnectionInterface(ABC):
    pass

class SourceInterface(ABC):
    pass

class TriggerInterface(ABC):
    pass

class ReporterInterface(ABC):
    pass

class Driver(ABC):
    """
    Base Driver class (Factory).
    Returns instances of connections, sources, triggers, and reporters.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the driver (e.g., 'gerrit')"""
        pass
        
    @abstractmethod
    def getConnection(self) -> ConnectionInterface:
        pass
        
    @abstractmethod
    def getSource(self) -> SourceInterface:
        pass
        
    @abstractmethod
    def getTrigger(self) -> TriggerInterface:
        pass
        
    @abstractmethod
    def getReporter(self) -> ReporterInterface:
        pass
