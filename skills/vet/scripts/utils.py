#!/usr/bin/env python3
"""Shared utilities for session export scripts."""

import sys


def log_warning(msg: str) -> None:
    """Log warnings to stderr so they don't interfere with stdout output."""
    print(f"WARNING: {msg}", file=sys.stderr)
