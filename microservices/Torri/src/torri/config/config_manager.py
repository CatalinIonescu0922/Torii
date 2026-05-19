"""
Configuration management for Torri services.

Reads INI-format configuration file and exposes settings for:
- Scheduler
- Merger  
- Gerrit connection
- Kafka connection
- Redis connection
- Web service
- Logging
- Monitoring
"""

import configparser
import os
from typing import Dict, Optional, Any
from shared.logger_setup import get_logger


class ConfigurationManager:
    """
    Central configuration manager for all Torri services.
    
    Reads from INI file: src/torri/config/torii.conf
    
    Provides access to all service configurations via properties.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to torii.conf file. If None, uses default location.
        """
        self.logger = get_logger('torri.config.manager')
        
        if not config_file:
            # Default location relative to this file
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(base_dir, 'torii.conf')
        
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        
        self.logger.info(f"Loading configuration from: {config_file}")
        
        if not os.path.exists(config_file):
            self.logger.error(f"Configuration file not found: {config_file}")
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        self.config.read(config_file)
        self.logger.info(f"Configuration loaded successfully. Sections: {self.config.sections()}")
    
    # ============================================================
    # Scheduler Configuration
    # ============================================================
    
    @property
    def scheduler_config_dir(self) -> str:
        """Directory containing YAML configuration files."""
        return self._get_value('scheduler', 'config_dir', 'src/torri/config/layout')
    
    @property
    def scheduler_pipelines_file(self) -> str:
        """Pipelines YAML file name."""
        return self._get_value('scheduler', 'pipelines_file', 'pipelines.yaml')
    
    @property
    def scheduler_projects_file(self) -> str:
        """Projects YAML file name."""
        return self._get_value('scheduler', 'projects_file', 'projects.yaml')
    
    @property
    def scheduler_jobs_file(self) -> str:
        """Jobs YAML file name."""
        return self._get_value('scheduler', 'jobs_file', 'jobs.yaml')
    
    @property
    def scheduler_queue_max_size(self) -> int:
        """Maximum number of changes in queue."""
        return self._get_int('scheduler', 'queue_max_size', 1000)
    
    @property
    def scheduler_queue_timeout(self) -> int:
        """Queue timeout in seconds."""
        return self._get_int('scheduler', 'queue_timeout_seconds', 300)
    
    @property
    def scheduler_driver(self) -> str:
        """VCS driver type (gerrit, github, gitlab, bitbucket, etc.)"""
        return self._get_value('scheduler', 'driver', 'gerrit')
    
    # ============================================================
    # File Paths
    # ============================================================
    
    @property
    def pipelines_yaml_path(self) -> str:
        """Full path to pipelines.yaml."""
        return os.path.join(self.scheduler_config_dir, self.scheduler_pipelines_file)
    
    @property
    def projects_yaml_path(self) -> str:
        """Full path to projects.yaml."""
        return os.path.join(self.scheduler_config_dir, self.scheduler_projects_file)
    
    @property
    def jobs_yaml_path(self) -> str:
        """Full path to jobs.yaml."""
        return os.path.join(self.scheduler_config_dir, self.scheduler_jobs_file)
    
    # ============================================================
    # Redis Configuration
    # ============================================================
    
    @property
    def redis_url(self) -> str:
        """Full Redis connection URL. Reads url from [connection redis] or assembles from host/port/db."""
        fallback = f"redis://{self._get_value('connection redis', 'host', 'localhost')}:{self._get_int('connection redis', 'port', 6379)}/{self._get_int('connection redis', 'db', 0)}"
        return self._get_value('scheduler', 'redis_url', None) or self._get_value('connection redis', 'url', fallback)
    
    @property
    def redis_password(self) -> Optional[str]:
        """Redis password (optional)."""
        pwd = self._get_value('connection redis', 'password', '')
        return pwd if pwd else None
    
    # ============================================================
    # Gerrit Configuration
    # ============================================================
    
    @property
    def gerrit_server(self) -> str:
        """Gerrit server hostname."""
        return self._get_value('connection gerrit', 'server', 'localhost')
    
    @property
    def gerrit_user(self) -> str:
        """Gerrit username."""
        return self._get_value('connection gerrit', 'user', 'ci-account')
    
    @property
    def gerrit_password(self) -> Optional[str]:
        """Gerrit password."""
        return self._get_value('connection gerrit', 'password')
    
    @property
    def gerrit_sshkey(self) -> Optional[str]:
        """SSH key path for Gerrit."""
        return self._get_value('connection gerrit', 'sshkey')
    
    @property
    def gerrit_ssh_port(self) -> int:
        """Gerrit SSH port."""
        return self._get_int('connection gerrit', 'ssh_port', 29418)
    
    @property
    def gerrit_rest_port(self) -> int:
        """Gerrit REST API port."""
        return self._get_int('connection gerrit', 'gerrit_rest_port', 8080)
    
    @property
    def gerrit_rest_https(self) -> bool:
        """Use HTTPS for Gerrit REST API."""
        return self._get_bool('connection gerrit', 'gerrit_rest_https', False)

    @property
    def gerrit_base_url(self) -> str:
        """Full base URL for the Gerrit REST API, including any path prefix."""
        protocol = 'https' if self.gerrit_rest_https else 'http'
        fallback = f"{protocol}://{self.gerrit_server}:{self.gerrit_rest_port}"
        return self._get_value('connection gerrit', 'base_url', fallback)
    
    @property
    def gerrit_rest_url(self) -> str:
        """Build full Gerrit REST API URL."""
        protocol = 'https' if self.gerrit_rest_https else 'http'
        return f"{protocol}://{self.gerrit_server}:{self.gerrit_rest_port}/a"
    
    # ============================================================
    # Kafka Configuration
    # ============================================================
    
    @property
    def kafka_bootstrap_servers(self) -> str:
        """Kafka bootstrap servers (comma-separated)."""
        return self._get_value('connection kafka', 'bootstrap_servers', 'kafka:9092')
    
    @property
    def kafka_bootstrap_servers_list(self) -> list:
        """Kafka bootstrap servers as list."""
        return [s.strip() for s in self.kafka_bootstrap_servers.split(',')]
    
    @property
    def kafka_group_scheduler(self) -> str:
        """Kafka consumer group for scheduler."""
        return self._get_value('connection kafka', 'group_scheduler', 'scheduler')
    
    @property
    def kafka_group_merger(self) -> str:
        """Kafka consumer group for merger."""
        return self._get_value('connection kafka', 'group_merger', 'merger')
    
    @property
    def kafka_topic_merger_requests(self) -> str:
        """Kafka topic for merger requests."""
        return self._get_value('connection kafka', 'topic_merger_requests', 'merger-requests')
    
    @property
    def kafka_topic_merger_responses(self) -> str:
        """Kafka topic for merger responses."""
        return self._get_value('connection kafka', 'topic_merger_responses', 'merger-responses')
    
    @property
    def kafka_topic_gerrit_events(self) -> str:
        """Kafka topic for Gerrit events."""
        return self._get_value('connection kafka', 'topic_gerrit_events', 'gerrit-events')
    
    @property
    def kafka_topic_gerrit_stream(self) -> str:
        """Kafka topic for raw Gerrit stream events."""
        return self._get_value('connection kafka', 'topic_gerrit_stream', 'gerrit-stream-events')
    
    @property
    def kafka_topic_trigger_events(self) -> str:
        """Kafka topic for enriched trigger events."""
        return self._get_value('connection kafka', 'topic_trigger_events', 'trigger-events')
    
    @property
    def kafka_group_gerrit_stream(self) -> str:
        """Kafka consumer group for gerrit stream."""
        return self._get_value('connection kafka', 'group_gerrit_stream', 'gerrit-stream-consumer-group')
    
    @property
    def kafka_group_trigger(self) -> str:
        """Kafka consumer group for trigger events."""
        return self._get_value('connection kafka', 'group_trigger', 'trigger-consumer-group')
    
    @property
    def kafka_compression_type(self) -> str:
        """Kafka compression type."""
        return self._get_value('connection kafka', 'compression_type', 'gzip')
    
    @property
    def kafka_acks(self) -> str:
        """Kafka producer acks setting."""
        return self._get_value('connection kafka', 'acks', 'all')
    
    # ============================================================
    # Merger Configuration
    # ============================================================
    
    @property
    def merger_git_dir(self) -> str:
        """Git working directory for merger."""
        return self._get_value('merger', 'git_dir', '/tmp/torri/merger-git')

    @property
    def merger_base_url(self) -> str:
        """HTTP base URL of the merger git server (used by executor to clone speculative refs)."""
        return self._get_value('merger', 'base_url', 'http://merger:8080')
    
    @property
    def merger_git_user_email(self) -> str:
        """Git user email for commits."""
        return self._get_value('merger', 'git_user_email', 'torri@example.com')
    
    @property
    def merger_git_user_name(self) -> str:
        """Git user name for commits."""
        return self._get_value('merger', 'git_user_name', 'Torri CI')
    
    # ============================================================
    # Web Configuration
    # ============================================================
    
    @property
    def web_enabled(self) -> bool:
        """Is web UI enabled."""
        return self._get_bool('web', 'enabled', True)
    
    @property
    def web_host(self) -> str:
        """Web UI bind host."""
        return self._get_value('web', 'host', '0.0.0.0')
    
    @property
    def web_port(self) -> int:
        """Web UI port."""
        return self._get_int('web', 'port', 8000)
    
    @property
    def web_root_url(self) -> str:
        """Web UI root URL."""
        return self._get_value('web', 'root_url', 'http://localhost:8000')
    
    # ============================================================
    # Logging Configuration
    # ============================================================
    
    @property
    def logging_level(self) -> str:
        """Logging level."""
        return self._get_value('logging', 'level', 'INFO')
    
    @property
    def logging_file(self) -> str:
        """Log file path."""
        return self._get_value('logging', 'file', '/var/log/torri/scheduler.log')
    
    @property
    def logging_format(self) -> str:
        """Log format string."""
        return self._get_value('logging', 'format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # ============================================================
    # Helper Methods
    # ============================================================
    
    def _get_value(self, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value."""
        try:
            return self.config.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            if default is not None:
                self.logger.debug(f"Config {section}.{key} not found, using default: {default}")
                return default
            self.logger.warning(f"Config {section}.{key} not found and no default provided")
            return None
    
    def _get_int(self, section: str, key: str, default: int = 0) -> int:
        """Get integer configuration value."""
        try:
            return self.config.getint(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            self.logger.debug(f"Config {section}.{key} not found or invalid, using default: {default}")
            return default
    
    def _get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """Get boolean configuration value."""
        try:
            return self.config.getboolean(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            self.logger.debug(f"Config {section}.{key} not found or invalid, using default: {default}")
            return default
    
    def get_section(self, section: str) -> Dict[str, str]:
        """Get entire configuration section as dict."""
        try:
            return dict(self.config.items(section))
        except configparser.NoSectionError:
            self.logger.warning(f"Configuration section not found: {section}")
            return {}
    
    def to_dict(self) -> Dict[str, Dict[str, str]]:
        """Export all configuration as nested dict."""
        result = {}
        for section in self.config.sections():
            result[section] = dict(self.config.items(section))
        return result
    
    def validate_files_exist(self) -> bool:
        """
        Validate that all YAML configuration files exist.
        
        Returns:
            bool: True if all files exist, False otherwise
        """
        files_to_check = [
            ('pipelines', self.pipelines_yaml_path),
            ('projects', self.projects_yaml_path),
            ('jobs', self.jobs_yaml_path),
        ]
        
        all_exist = True
        for name, path in files_to_check:
            if not os.path.exists(path):
                self.logger.error(f"{name} file not found: {path}")
                all_exist = False
            else:
                self.logger.info(f"{name} file found: {path}")
        
        return all_exist
    
    def get_connection_settings(self, connection_name: str) -> Dict[str, str]:
        """
        Get settings for a specific connection.
        
        Args:
            connection_name: Name of connection (gerrit, kafka, redis, etc.)
        
        Returns:
            Dict of connection settings
        """
        return self.get_section(f'connection {connection_name}')


# Global configuration instance
_config_manager: Optional[ConfigurationManager] = None


def initialize_config(config_file: Optional[str] = None) -> ConfigurationManager:
    """
    Initialize global configuration manager.
    
    Args:
        config_file: Optional path to config file
    
    Returns:
        ConfigurationManager instance
    """
    global _config_manager
    
    _config_manager = ConfigurationManager(config_file)
    return _config_manager


def get_config() -> ConfigurationManager:
    """
    Get global configuration manager instance.
    
    Returns:
        ConfigurationManager instance
    
    Raises:
        RuntimeError: If not initialized yet
    """
    global _config_manager
    
    if _config_manager is None:
        raise RuntimeError("Configuration not initialized. Call initialize_config() first.")
    
    return _config_manager
