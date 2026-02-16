"""Shared utilities for antaris-memory."""

import json
import os
import tempfile
import logging

logger = logging.getLogger("antaris_memory")


def atomic_write_json(path: str, data: dict, indent: int = 2) -> None:
    """Write JSON atomically using tmp file + os.replace.
    
    Prevents data corruption from interrupted writes or concurrent access.
    The write either fully completes or doesn't happen at all.
    """
    dir_path = os.path.dirname(path) or "."
    os.makedirs(dir_path, exist_ok=True)
    
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
