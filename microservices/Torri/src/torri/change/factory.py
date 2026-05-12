"""
Factory for creating Change instances.

Routes to appropriate VCS-specific Change implementation based on source.
"""

from typing import Dict, Optional
from shared.logger_setup import get_logger
from torri.change import Change, GerritChange


class ChangeFactory:
    """Factory for creating Change instances from events."""
    
    def __init__(self):
        """Initialize factory with connection registry."""
        self.logger = get_logger(__name__)
        self._connections: Dict[str, Dict] = {}
    
    def register_connection(self, source: str, connection_name: str, connection):
        """
        Register a connection for Change creation.
        
        Args:
            source: VCS type ('gerrit', 'github', 'gitlab')
            connection_name: Name of connection instance
            connection: Connection object (GerritRestConnection, etc.)
        """
        if source not in self._connections:
            self._connections[source] = {}
        
        self._connections[source][connection_name] = connection
        self.logger.debug(f"Registered {source} connection: {connection_name}")
    
    def create_change(self, source: str, connection_name: str, **kwargs) -> Optional[Change]:
        """
        Create a Change instance of the appropriate VCS type.
        
        Args:
            source: VCS type ('gerrit', 'github', 'gitlab')
            connection_name: Name of connection to use
            **kwargs: Additional arguments for the Change constructor
        
        Returns:
            Change instance or None if source not supported
        
        Raises:
            ValueError: If connection not registered
        """
        try:
            if source == 'gerrit':
                connection = self._get_connection(source, connection_name)
                change = GerritChange(connection_name, connection)
                
                # Set basic fields from kwargs
                for key, value in kwargs.items():
                    if hasattr(change, key):
                        setattr(change, key, value)
                
                self.logger.debug(f"Created GerritChange from {connection_name}")
                return change
            
            elif source == 'github':
                # TODO: Implement GitHubChange
                self.logger.warning(f"GitHub changes not yet implemented")
                return None
            
            elif source == 'gitlab':
                # TODO: Implement GitLabChange
                self.logger.warning(f"GitLab changes not yet implemented")
                return None
            
            else:
                self.logger.error(f"Unknown VCS source: {source}")
                return None
        
        except Exception as e:
            self.logger.error(f"Error creating change: {e}", exc_info=True)
            return None
    
    def _get_connection(self, source: str, connection_name: str):
        """
        Get registered connection instance.
        
        Args:
            source: VCS type
            connection_name: Name of connection
        
        Returns:
            Connection instance
        
        Raises:
            ValueError: If connection not registered
        """
        if source not in self._connections:
            raise ValueError(f"No {source} connections registered")
        
        if connection_name not in self._connections[source]:
            raise ValueError(
                f"Connection '{connection_name}' not registered for {source}"
            )
        
        return self._connections[source][connection_name]
    
    def supports_source(self, source: str) -> bool:
        """
        Check if factory supports a VCS source.
        
        Args:
            source: VCS type to check
        
        Returns:
            bool: True if supported
        """
        return source in ('gerrit', 'github', 'gitlab')
