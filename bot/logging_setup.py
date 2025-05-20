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

    # General console handler for all levels (INFO and above)
    # If you want only INFO to go to console, use only the handler above.
    # If you want INFO and higher (WARNING, ERROR, CRITICAL) to go to console, use this one.
    console_handler_all = logging.StreamHandler()
    console_handler_all.setFormatter(log_formatter)
    root_logger.addHandler(console_handler_all)


    # Specific logger for the application, if needed for finer control later
    # For now, root logger configuration is likely sufficient.
    # app_logger = logging.getLogger(__name__) # Or a specific app name like "tt_telegram_bot"
    # app_logger.setLevel(logging.INFO)
    # If app_logger has handlers, set propagate to False to avoid double logging with root.
    # app_logger.propagate = False

    # Example of file handler (optional)
    # file_handler = logging.FileHandler("bot.log")
    # file_handler.setFormatter(log_formatter)
    # root_logger.addHandler(file_handler)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__) # For this module
    logger.info("Logging configured.")
    return logger

# Call setup_logging() here or ensure it's called once at the start of your application.
# logger = setup_logging() # This line is if you want to use 'logger' from this module directly.
# It's generally better to call setup_logging() in main.py and then use logging.getLogger(__name__) in other modules.
