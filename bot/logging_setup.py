import logging
import sys
from bot.constants import LOG_FORMAT

def setup_logging():
    log_formatter = logging.Formatter(LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Main console handler for INFO and above
    console_handler_all = logging.StreamHandler(sys.stdout)
    console_handler_all.setFormatter(log_formatter)
    console_handler_all.setLevel(logging.INFO)
    root_logger.addHandler(console_handler_all)

    # Configure logging levels for specific noisy libraries
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__) # For this module
    logger.info("Logging configured.")
    return logger
