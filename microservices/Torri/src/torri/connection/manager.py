"""
Multi-connection manager.

Manages multiple VCS connections (Gerrit, GitHub, GitLab, etc.)
Routes normalized events to scheduler.

Design: Connection Aggregator Pattern
- Multiple connections feed events to single queue
- Scheduler processes events uniformly (source-agnostic)
- Easy to add new sources without modifying scheduler
"""

from typing import Dict, Optional, List
import threading
from queue import Queue, Empty

from shared.logger_setup import get_logger
from torri.connection.event_normalizer import TriggerEvent


class ConnectionManager:
    """
    Manages multiple VCS connections.
    
    Responsibilities:
    1. Register connections (Gerrit, GitHub, GitLab, etc.)
    2. Start/stop connection event processors
    3. Route normalized events to scheduler
    4. Handle connection failures and health
    """
    
    def __init__(self, max_queue_size: int = 10000):
        """
        Initialize connection manager.
        
        Args:
            max_queue_size: Maximum size of event queue
        """
        self.logger = get_logger('torri.connection.manager')
        self.connections: Dict[str, any] = {}  # name -> connection instance
        self.event_queue: Queue = Queue(maxsize=max_queue_size)
        self.scheduler = None
        self._lock = threading.RLock()
        self.logger.info(f"ConnectionManager initialized with queue size {max_queue_size}")
    
    def register_connection(self, name: str, connection) -> bool:
        """
        Register a new connection.
        
        Args:
            name: Connection name (from config, e.g., 'gerrit', 'github-public')
            connection: Connection instance (extends BaseConnection)
        
        Returns:
            bool: True if registered successfully
        """
        try:
            with self._lock:
                if name in self.connections:
                    self.logger.warning(f"Connection '{name}' already registered, replacing")
                
                self.connections[name] = connection
                
                # Register scheduler with connection if available
                if self.scheduler:
                    connection.registerScheduler(self)
                
                self.logger.info(f"Registered connection: {name} ({connection.__class__.__name__})")
                return True
        
        except Exception as e:
            self.logger.error(f"Failed to register connection '{name}': {e}")
            return False
    
    def get_connection(self, name: str) -> Optional[any]:
        """Get connection by name."""
        return self.connections.get(name)
    
    def get_connections(self) -> Dict[str, any]:
        """Get all connections."""
        return dict(self.connections)
    
    def register_scheduler(self, scheduler) -> None:
        """
        Register scheduler with manager.
        
        Scheduler receives normalized events via addEvent().
        """
        self.scheduler = scheduler
        self.logger.info("Scheduler registered with ConnectionManager")
        
        # Register scheduler with all existing connections
        for name, connection in self.connections.items():
            try:
                connection.registerScheduler(self)
            except Exception as e:
                self.logger.error(f"Failed to register scheduler with {name}: {e}")
    
    def start_all(self) -> bool:
        """
        Start all registered connections.
        
        Should be called during system startup.
        """
        success = True
        
        with self._lock:
            for name, connection in self.connections.items():
                try:
                    self.logger.info(f"Starting connection: {name}")
                    
                    # Call connection's onLoad if available
                    if hasattr(connection, 'onLoad'):
                        connection.onLoad()
                    
                    # Start event processor thread if available
                    if hasattr(connection, 'start_event_processor'):
                        connection.start_event_processor()
                    
                    self.logger.info(f"Connection started: {name}")
                
                except Exception as e:
                    self.logger.error(f"Failed to start connection '{name}': {e}", exc_info=True)
                    success = False
        
        return success
    
    def stop_all(self) -> bool:
        """
        Stop all registered connections.
        
        Should be called during system shutdown.
        """
        success = True
        
        with self._lock:
            for name, connection in self.connections.items():
                try:
                    self.logger.info(f"Stopping connection: {name}")
                    
                    # Stop event processor thread if available
                    if hasattr(connection, 'stop_event_processor'):
                        connection.stop_event_processor()
                    
                    # Call connection's onStop if available
                    if hasattr(connection, 'onStop'):
                        connection.onStop()
                    
                    self.logger.info(f"Connection stopped: {name}")
                
                except Exception as e:
                    self.logger.error(f"Failed to stop connection '{name}': {e}", exc_info=True)
                    success = False
        
        return success
    
    def add_event(self, event: TriggerEvent) -> bool:
        """
        Add event to queue for scheduler processing.
        
        Called by connection event processors after normalizing events.
        
        Args:
            event: Normalized TriggerEvent from any source
        
        Returns:
            bool: True if queued successfully
        """
        try:
            if not isinstance(event, TriggerEvent):
                self.logger.error(f"Invalid event type: {type(event)}")
                return False
            
            # Don't block - if queue is full, log and drop
            self.event_queue.put_nowait(event)
            
            self.logger.debug(
                f"Queued event: source={event.source} type={event.type} "
                f"project={event.project_name} change={event.change_id}"
            )
            
            return True
        
        except Exception as e:
            self.logger.error(f"Failed to queue event: {e}")
            return False
    
    def get_event(self, timeout: float = 1.0) -> Optional[TriggerEvent]:
        """
        Get next event from queue.
        
        Called by scheduler main loop to fetch events for processing.
        
        Args:
            timeout: Wait timeout in seconds
        
        Returns:
            TriggerEvent: Next event, or None if queue is empty
        """
        try:
            return self.event_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def get_queue_status(self) -> Dict[str, any]:
        """Get queue status for monitoring."""
        return {
            'queue_size': self.event_queue.qsize(),
            'queue_maxsize': self.event_queue.maxsize,
            'connections_count': len(self.connections),
            'connections': list(self.connections.keys()),
        }
    
    def get_health_status(self) -> Dict[str, any]:
        """Get health status of all connections."""
        status = {
            'total_connections': len(self.connections),
            'connections': {}
        }
        
        for name, connection in self.connections.items():
            conn_status = {
                'name': name,
                'class': connection.__class__.__name__,
            }
            
            # Check if connection has health method
            if hasattr(connection, 'get_health_status'):
                try:
                    conn_status['status'] = connection.get_health_status()
                except Exception as e:
                    conn_status['status'] = f"error: {e}"
            
            status['connections'][name] = conn_status
        
        return status
