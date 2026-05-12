import abc

class BaseConnection(metaclass=abc.ABCMeta):
    """Base class for connections.

    A connection is a shared object that sources, triggers and reporters can
    use to speak with a remote API without needing to establish a new
    connection each time or without having to authenticate each time.

    Multiple instances of the same connection may exist with different
    credentials, for example, thus allowing for different pipelines to operate
    on different Gerrit installations or post back as a different user etc.

    Connections can implement their own public methods. Required connection
    methods are validated by the {trigger, source, reporter} they are loaded
    into. For example, a trigger will likely require some kind of query method
    while a reporter may need a review method.
    
    Multi-Connection Support:
    - Each connection normalizes events to unified TriggerEvent format
    - registerScheduler() receives ConnectionManager (not scheduler directly)
    - Events dispatched via connection_manager.add_event(event)
    """

    def __init__(self, connection_name, connection_config):
        # connection_name is the name given to this connection in zuul.ini
        # connection_config is a dictionary of config_section from zuul.ini for
        # this connection.
        # __init__ shouldn't make the actual connection in case this connection
        # isn't used in the layout.
        self.connection_name = connection_name
        self.connection_config = connection_config
        self.attached_to = {}

        # Keep track of the sources, triggers and reporters using this
        # connection

    def onLoad(self):
        """Placeholder for actions to take when the connection is loaded"""

    def onStop(self):
        """Placeholder for actions to take when the connection is stopped"""

    def registerScheduler(self, sched):
        """
        Register scheduler or connection manager with this connection.
        
        Args:
            sched: Scheduler instance or ConnectionManager instance
        
        In multi-connection setup, this receives ConnectionManager.
        Connection uses it to dispatch normalized events via sched.add_event(event).
        """
        self.sched = sched

    def registerUse(self, what, instance):
        """Registers an object instance that uses this connection"""
        if what not in self.attached_to:
            self.attached_to[what] = []
        self.attached_to[what].append(instance)
        
    def __repr__(self):
        return '<Connection 0x%x %s %s>' % (id(self), self.connection_name, getattr(self, 'driver_name', ''))


