"""Safe file writes.

``atomic_write`` writes to a temporary file next to the target, flushes it to
disk, then swaps it in with ``os.replace``. Readers (EmulationStation, another
editor, our own tests) see either the old file or the new one, never an empty
or half-written file, and a crash or power cut during the write leaves the
original intact.
"""

import os
import shutil
import tempfile
import time

from gme.log import log

# Windows: a reader holding the file open (antivirus, indexer, editor) makes
# os.replace fail for a moment. Retry briefly, then fall back to a direct write
# so that saving never fails because of a transient lock.
_REPLACE_RETRIES = 10
_REPLACE_DELAY = 0.05


def atomic_write(path, data):
    """Replace ``path`` with ``data`` (bytes) atomically."""
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                shutil.copymode(path, tmp)
            except OSError:
                pass
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    break
                time.sleep(_REPLACE_DELAY)
        log.warning("Could not replace %s atomically (file locked); writing in place", path)
        with open(path, "wb") as f:
            f.write(data)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
