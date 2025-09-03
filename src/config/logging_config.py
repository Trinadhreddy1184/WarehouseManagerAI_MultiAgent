import logging
import os
from typing import Optional


def setup_logging(level: Optional[str] = None) -> None:
    """Configure root logging.

    Parameters
    ----------
    level: optional str
        Logging level name; overrides the ``LOG_LEVEL`` environment variable if
        provided.  Defaults to ``INFO`` when neither is supplied.
    """
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = level.upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
