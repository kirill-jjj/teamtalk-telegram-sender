import logging
from bot.constants import LOG_FORMAT

class InfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.INFO

def setup_logging():
    log_formatter = logging.Formatter(LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler for INFO messages
    console_handler_info = logging.StreamHandler()
    console_handler_info.setFormatter(log_formatter)
    console_handler_info.addFilter(InfoFilter())
    # root_logger.addHandler(console_handler_info) # This would duplicate INFO to console if general handler is also added

    console_handler_all = logging.StreamHandler()
    console_handler_all.setFormatter(log_formatter)
    root_logger.addHandler(console_handler_all)




    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__) # For this module
    logger.info("Logging configured.")
    return logger

