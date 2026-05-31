from abc import ABC, abstractmethod
from torri.driver import ConnectionInterface

class BaseConnection(ConnectionInterface):
    """
    Base connection. Stateful, handles auth, network, and caching.
    """
    def __init__(self, driver, connection_name, connection_config):
        self.driver = driver
        self.connection_name = connection_name
        self.connection_config = connection_config