import logging
import sys
from bot.constants import LOG_FORMAT

def setup_logging():
    log_formatter = logging.Formatter(LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    console_handler_all = logging.StreamHandler(sys.stdout)
    console_handler_all.setFormatter(log_formatter)
    console_handler_all.setLevel(logging.INFO)
    root_logger.addHandler(console_handler_all)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging configured.")
    return logger
