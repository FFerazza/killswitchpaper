"""Logging setup: all pipeline stages log to stderr, timestamps in ISO 8601 UTC."""

import logging
import sys
import time


def get_logger(name: str) -> logging.Logger:
    """Return a logger writing ISO-8601-UTC-stamped lines to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
