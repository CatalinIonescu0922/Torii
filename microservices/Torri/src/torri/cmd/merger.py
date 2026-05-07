from . import TorriCLI
from shared.logger_setup import setup_logging
import os
from pathlib import Path

def run_server(args):
    # We load the setup_logging immediately before loading internal architecture
    # Providing the required dummy paths since we are passing them explicitly now
    base_dir = Path(__file__).resolve().parent.parent
    config_yaml = base_dir / "config" / "log" / "main_logging.yaml"
    
    setup_logging(
        config_path=str(config_yaml), 
        service_root=Path(os.getenv("MERGER_WORKSPACE_PATH", "/tmp/"))
    )
    
    from torri.merger.server import KafkaConsumerWorker
    worker = KafkaConsumerWorker()
    worker.run()

def main():
    cli = TorriCLI(description="Torri Merger")
    cli.run(run_server)

if __name__ == "__main__":
    main()
