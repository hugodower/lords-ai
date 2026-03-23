import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"[LORDS-AI] {name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s — %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger
