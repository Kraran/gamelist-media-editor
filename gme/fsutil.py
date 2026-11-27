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

# Windows: a reader holding the file open (antivirus, indexer, editor) makes
# os.replace fail for a moment. Retry briefly, then report the lock without
# truncating the original file.
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
                    raise
                time.sleep(_REPLACE_DELAY)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def trash(path):
    """Move a file or a folder to the Recycle Bin (recoverable).

    Raises OSError (or send2trash's TrashPermissionError) when the drive has
    no Recycle Bin, e.g. some network shares: callers then keep the file.
    """
    from send2trash import send2trash
    send2trash(path)
    try:                                      # the undo step says it is in the Recycle Bin
        from gme import history
        history.note_trash()
    except Exception:  # pragma: no cover
        pass
