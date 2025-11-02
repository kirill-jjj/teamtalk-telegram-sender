"""Logging configuration for the application."""

import logging
import sys

from bot.core.constants import LOG_FORMAT


def setup_logging() -> logging.Logger:
    """Configures and returns the root logger for the application.

    Sets up console handlers with specified formatting and levels.
    Also adjusts levels for noisy Aiogram loggers.

    Returns:
        The configured root logger instance.
    """
    log_formatter = logging.Formatter(LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler_all = logging.StreamHandler(sys.stdout)
    console_handler_all.setFormatter(log_formatter)
    console_handler_all.setLevel(logging.INFO)
    root_logger.addHandler(console_handler_all)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
    logging.getLogger("aiogram.middlewares").setLevel(logging.WARNING)
    logging.getLogger("alembic.runtime.migration").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.debug("Logging configured.")
    return logger
