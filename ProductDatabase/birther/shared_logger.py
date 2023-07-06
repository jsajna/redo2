"""
Shared logger creation. To make sure all modules get the correct, formatted
logger, regardless how they're used.
"""

from datetime import datetime
import getpass
import logging
import socket

# from . import paths

LOG_FORMAT = "%(asctime)s %(module)s %(levelname)s: %(message)s"
LOG_FILENAME = f"{datetime.now().date()}_{socket.gethostname()}_{getpass.getuser()}.txt"

logger = logging.getLogger("ProductDatabase_Django")
logger.setLevel(logging.DEBUG)
logging.basicConfig(format=LOG_FORMAT)
