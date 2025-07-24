import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(name)10s | %(levelname)-7s | %(message)s"
)


def get_logger():
    return logging.getLogger("catscan")
