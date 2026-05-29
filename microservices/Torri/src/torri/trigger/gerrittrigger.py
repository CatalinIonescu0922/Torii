import re
from typing import List

from torri.model import BaseEventFilter
from torri.trigger import BaseTrigger


class GerritEventFilter(BaseEventFilter):
    """
    One trigger rule from the `trigger: gerrit:` section of a pipeline.

    Example YAML entry:
        - event: comment-added
          comment:
            - ^recheck$
    """

    def __init__(self, config: dict):
        self.event_type = config.get('event')
        comment_patterns = config.get('comment') or []
        self.comment_regexes = [re.compile(p) for p in comment_patterns]

    def matches(self, event) -> bool:
        if self.event_type and event.type != self.event_type:
            return False
        # If comment patterns are set, at least one must match.
        if self.comment_regexes:
            return any(r.search(event.comment or '') for r in self.comment_regexes)
        return True


class GerritTrigger(BaseTrigger):
    """
    Gerrit implementation of BaseTrigger.
    Converts the raw YAML list under `trigger: gerrit:` into GerritEventFilter objects.
    """

    def getEventFilters(self, config_list: list) -> List[GerritEventFilter]:
        return [
            GerritEventFilter(item)
            for item in config_list
            if isinstance(item, dict)
        ]
