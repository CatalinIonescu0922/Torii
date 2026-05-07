"""
init for torri source
"""
import abc

class BaseSource(metaclass=abc.ABCMeta):
    """Base class for sources.

    A source class gives methods for fetching and updating changes. Each
    pipeline must have (only) one source. It is the canonical provider of the
    change to be tested.

    Defines the exact public methods that must be supplied."""

    def __init__(self, source_config=None, sched=None, connection=None):
        source_config = source_config if source_config else {}
        self.source_config = source_config
        self.sched = sched
        self.connection = connection

    def stop(self):
        """Stop the source."""

    @abc.abstractmethod
    def getRefSha(self, change):
        """Return a sha for a given change object."""

    @abc.abstractmethod
    def isMerged(self, change, head=None):
        """Determine if change is merged.

        If head is provided the change is checked if it is at head."""

    @abc.abstractmethod
    def canMerge(self, change, allow_needs):
        """Determine if change can merge."""

    def postConfig(self):
        """Called after configuration has been processed."""

    @abc.abstractmethod
    def getChange(self, event, project, refresh):
        """Get the change representing an event."""

    @abc.abstractmethod
    def getProjectOpenChanges(self, project):
        """Get the open changes for a project."""

    @abc.abstractmethod
    def getGitUrl(self, project):
        """Get the git url for a project."""

    # @abc.abstractmethod
    def getGitUrlStr(self, project):
        """Get the git url for a project as string."""


