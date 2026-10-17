"""Shared logger (console output of the local server)."""

import logging


log = logging.getLogger("gamelist-editor")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
