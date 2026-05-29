from abc import ABC, abstractmethod


class BaseEventFilter(ABC):
    """
    Represents one trigger rule from a pipeline's trigger: section.
    Each filter knows whether a given event satisfies its rule.
    """

    @abstractmethod
    def matches(self, event) -> bool:
        pass


class BaseReporterAction(ABC):
    """
    Represents one reporting task: post a comment, leave a vote, etc.
    All the data needed to execute the action is baked in at construction time.
    """

    @abstractmethod
    def report(self, change_id: str, patchset: str) -> None:
        pass
