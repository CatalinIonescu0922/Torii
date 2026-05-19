from . import TorriCLI
from shared.logger_setup import setup_logging
import os
from pathlib import Path

def run_server(args):
    # Use shared logging configuration from /app/config/log/
    config_yaml = Path("/app/config/log/main_logging.yaml")
    
    # Resolve log paths relative to merger workspace (container /app)
    service_root = Path(os.getenv("MERGER_WORKSPACE_PATH", "/app"))
    setup_logging(
        config_path=str(config_yaml), 
        service_root=service_root
    )
    
    from torri.merger.server import KafkaConsumerWorker
    worker = KafkaConsumerWorker()
    worker.run()

def main():
    cli = TorriCLI(description="Torri Merger")
    cli.run(run_server)

if __name__ == "__main__":
    main()
