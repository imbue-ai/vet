"""Entry point for running vet-history as a module.

Usage:
    python -m vet_history <command> [options]
"""

import sys

from vet_history.cli import main

if __name__ == "__main__":
    sys.exit(main())
