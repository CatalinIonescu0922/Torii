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
    A single reporter action produced from a pipeline's success/failure section.
    Holds the labels and message baked in at config load time.
    The scheduler calls report(change_id, patchset) without knowing the driver.
    """

    @abstractmethod
    def report(self, change_id: str, patchset: str) -> None:
        pass

