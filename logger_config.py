import logging
import sys
import os
from pythonjsonlogger import jsonlogger


def setup_logger(name="vm_manager"):
    logger = logging.getLogger(name)

    # Set default level to WARNING, allow override via LOG_LEVEL env var
    level_name = os.environ.get("LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logger.setLevel(level)

    logHandler = logging.FileHandler("vm_manager.log")
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)

    # Also log to stdout for debugging if needed, but in standard format
    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(consoleHandler)

    return logger


logger = setup_logger()
