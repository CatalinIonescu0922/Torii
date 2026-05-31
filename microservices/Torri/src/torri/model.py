from abc import ABC, abstractmethod


class BaseEventFilter(ABC):
    """
    Represents one trigger rule from a pipeline's trigger: section.
    Each filter knows whether a given event satisfies its rule.
    """

    @abstractmethod
    def matches(self, event) -> bool:
        pass

