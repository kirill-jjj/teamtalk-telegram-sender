import logging
import sys # Added for sys.stdout
from bot.constants import LOG_FORMAT

def setup_logging():
    log_formatter = logging.Formatter(LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) # Changed to DEBUG

    # Main console handler for INFO and above
    console_handler_all = logging.StreamHandler(sys.stdout) # Explicitly use sys.stdout
    console_handler_all.setFormatter(log_formatter)
    console_handler_all.setLevel(logging.INFO) # Set to INFO
    root_logger.addHandler(console_handler_all)

    # Removed console_handler_info and its setup as it's now redundant

    # Configure logging levels for specific noisy libraries
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__) # For this module
    logger.info("Logging configured.")
    return logger

