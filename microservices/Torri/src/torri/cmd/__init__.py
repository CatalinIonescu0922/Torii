import argparse

class TorriCLI:
    """Abstracts the logic of creating a CLI app with argument parsing."""
    def __init__(self, description="Torri Microservice"):
        self.parser = argparse.ArgumentParser(description=description)
        self.parser.add_argument('-d', '--nodaemon', action='store_true', help='Do not daemonize. Run in foreground.')
        self.parser.add_argument('-c', '--config', help='Path to configuration file')

    def parse_args(self):
        return self.parser.parse_args()

    def run(self, main_func):
        args = self.parse_args()
        main_func(args)
