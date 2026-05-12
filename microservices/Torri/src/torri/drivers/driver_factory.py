"""
Driver factory - selects driver implementations based on configuration.

Design: Open/Closed principle - add new drivers without modifying core code.
"""

from typing import Dict, Any, Tuple

from shared.logger_setup import get_logger
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


logger = get_logger(__name__)


class DriverFactory:
    """
    Factory for creating driver instances based on configuration.
    
    Supports multiple VCS systems by selecting appropriate driver implementations.
    Adding GitHub support: Just add GitHubChangeSource, etc., and update factory.
    No changes needed to core scheduler code.
    """
    
    SUPPORTED_DRIVERS = {
        'gerrit': {
            'change_source': GerritChangeSource,
            'validation_gate': GerritValidationGate,
            'merge_driver': GerritMergeDriver,
            'synthetic_ref_provider': GerritSyntheticRefProvider,
        },
        # Future: GitHub, GitLab, Bitbucket, etc.
        # 'github': {...},
        # 'gitlab': {...},
    }
    
    @staticmethod
    def create_drivers(
        driver_type: str,
        config: 'ConfigurationManager',
        components: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Create driver instances for specified VCS system.
        
        Args:
            driver_type: Driver identifier ('gerrit', 'github', 'gitlab', etc.)
            config: ConfigurationManager instance
            components: Initialized components (gerrit_conn, entry_gate, etc.)
        
        Returns:
            (success: bool, drivers_dict: Dict[str, driver_instance])
        """
        logger.info(f"Creating {driver_type} drivers")
        
        if driver_type not in DriverFactory.SUPPORTED_DRIVERS:
            logger.error(f"Unsupported driver type: {driver_type}")
            return False, {}
        
        try:
            driver_specs = DriverFactory.SUPPORTED_DRIVERS[driver_type]
            drivers = {}
            
            # Create ChangeSource
            if driver_type == 'gerrit':
                drivers['change_source'] = GerritChangeSource()
                logger.info("Created GerritChangeSource")
            
            # Create ValidationGate  
            if driver_type == 'gerrit':
                drivers['validation_gate'] = GerritValidationGate(
                    components['entry_gate']
                )
                logger.info("Created GerritValidationGate")
            
            # Create MergeDriver
            if driver_type == 'gerrit':
                drivers['merge_driver'] = GerritMergeDriver(
                    components['gerrit']
                )
                logger.info("Created GerritMergeDriver")
            
            # Create SyntheticRefProvider
            if driver_type == 'gerrit':
                drivers['synthetic_ref_provider'] = GerritSyntheticRefProvider(
                    components['merger_coordinator']
                )
                logger.info("Created GerritSyntheticRefProvider")
            
            logger.info(f"All {driver_type} drivers created successfully")
            return True, drivers
        
        except Exception as e:
            logger.error(f"Failed to create {driver_type} drivers: {e}", exc_info=True)
            return False, {}
    
    @staticmethod
    def get_supported_drivers() -> list:
        """Get list of supported driver types."""
        return list(DriverFactory.SUPPORTED_DRIVERS.keys())
    
    @staticmethod
    def validate_driver_type(driver_type: str) -> bool:
        """Check if driver type is supported."""
        return driver_type in DriverFactory.SUPPORTED_DRIVERS
