"""
Internal event representations for Torri scheduler.

All VCS sources normalize to NormalizedEvent format for uniform processing.
"""

from torri.events.normalized_event import NormalizedEvent, EventType


__all__ = [
    'NormalizedEvent',
    'EventType',
]
