import sys

from loguru import logger


def configure_logging(level: str, json_logs: bool) -> None:
    logger.remove()
    logger.add(sys.stdout, level=level, serialize=json_logs, backtrace=False, diagnose=False)
