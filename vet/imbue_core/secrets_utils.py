import os


def get_secret(secret_name: str) -> str | None:
    """Get a secret from environment variables."""
    return os.environ.get(secret_name)
