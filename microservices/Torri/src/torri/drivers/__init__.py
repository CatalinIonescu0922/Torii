"""
Torri driver abstraction layer.

Supports multiple source control and CI/CD systems through driver pattern:
- ChangeSource: Receive and parse changes from VCS events
- ValidationGate: Validate pipeline entry criteria
- MergeDriver: Submit/merge changes in VCS
- SyntheticRefProvider: Create synthetic refs for testing

This design allows easy extension (GitHub, GitLab, Bitbucket) without modifying core scheduler.
"""

from torri.drivers.base_drivers import (
    ChangeSource,
    ValidationGate,
    MergeDriver,
    SyntheticRefProvider,
)
from torri.drivers.gerrit_drivers import (
    GerritChangeSource,
    GerritValidationGate,
    GerritMergeDriver,
    GerritSyntheticRefProvider,
)
from torri.drivers.driver_factory import DriverFactory


__all__ = [
    'ChangeSource',
    'ValidationGate',
    'MergeDriver',
    'SyntheticRefProvider',
    'GerritChangeSource',
    'GerritValidationGate',
    'GerritMergeDriver',
    'GerritSyntheticRefProvider',
    'DriverFactory',
]
