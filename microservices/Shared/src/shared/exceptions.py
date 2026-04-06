class GerritQueryError(Exception):
    """Raised when a Gerrit REST query fails after retries."""
