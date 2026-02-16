"""
Cross-platform file locking using lock directories.

Uses os.mkdir() for atomic lock acquisition — portable across POSIX and Windows,
works on network filesystems, zero dependencies.

Usage:
    lock = FileLock("/path/to/resource.json")
    with lock:
        data = load(resource)
        modify(data)
        save(resource, data)

    # Or with timeout:
    with FileLock("/path/to/resource.json", timeout=5.0):
        ...

    # Non-blocking try:
    lock = FileLock("/path/to/resource.json")
    if lock.acquire(blocking=False):
        try:
            ...
        finally:
            lock.release()
"""

import os
import time
import json
import logging

logger = logging.getLogger("antaris_memory")

# Stale lock threshold — if a lock is older than this, assume the holder crashed
STALE_LOCK_SECONDS = 300  # 5 minutes


class LockTimeout(Exception):
    """Raised when a lock cannot be acquired within the timeout."""
    pass


class FileLock:
    """Cross-platform file lock using mkdir().
    
    os.mkdir() is atomic on all major platforms and filesystems.
    The lock directory contains a metadata file with holder info
    for debugging stale locks.
    
    Args:
        path: Path to the resource being locked (the .lock dir is derived from this)
        timeout: Maximum seconds to wait for lock acquisition (None = wait forever)
        poll_interval: Seconds between acquisition attempts
        stale_threshold: Seconds after which an unrefreshed lock is considered stale
    """
    
    def __init__(self, path: str, timeout: float = 30.0, 
                 poll_interval: float = 0.05, stale_threshold: float = STALE_LOCK_SECONDS):
        self.path = path
        self.lock_dir = path + ".lock"
        self.meta_path = os.path.join(self.lock_dir, "holder.json")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.stale_threshold = stale_threshold
        self._held = False
    
    def acquire(self, blocking: bool = True) -> bool:
        """Acquire the lock.
        
        Args:
            blocking: If True, wait up to self.timeout. If False, return immediately.
            
        Returns:
            True if lock acquired, False if non-blocking and lock unavailable.
            
        Raises:
            LockTimeout: If blocking and timeout exceeded.
        """
        start = time.monotonic()
        
        while True:
            try:
                os.mkdir(self.lock_dir)
                # Lock acquired — write holder metadata
                self._write_meta()
                self._held = True
                logger.debug(f"Lock acquired: {self.lock_dir}")
                return True
            except OSError:
                # Lock directory exists — check if stale
                if self._break_stale():
                    continue  # Stale lock broken, retry immediately
                
                if not blocking:
                    return False
                
                elapsed = time.monotonic() - start
                if self.timeout is not None and elapsed >= self.timeout:
                    raise LockTimeout(
                        f"Could not acquire lock on {self.path} "
                        f"after {self.timeout:.1f}s (holder: {self._read_holder()})"
                    )
                
                time.sleep(self.poll_interval)
    
    def release(self):
        """Release the lock."""
        if not self._held:
            return
        
        try:
            # Remove metadata file first, then lock directory
            if os.path.exists(self.meta_path):
                os.unlink(self.meta_path)
            os.rmdir(self.lock_dir)
            logger.debug(f"Lock released: {self.lock_dir}")
        except OSError as e:
            logger.warning(f"Error releasing lock {self.lock_dir}: {e}")
        finally:
            self._held = False
    
    def _write_meta(self):
        """Write lock holder metadata for debugging."""
        try:
            meta = {
                "pid": os.getpid(),
                "acquired_at": time.time(),
                "path": self.path,
            }
            with open(self.meta_path, "w") as f:
                json.dump(meta, f)
        except OSError:
            pass  # Non-critical — lock is held regardless
    
    def _read_holder(self) -> str:
        """Read holder info for error messages."""
        try:
            with open(self.meta_path) as f:
                meta = json.load(f)
            return f"pid={meta.get('pid')}, acquired={meta.get('acquired_at')}"
        except (OSError, json.JSONDecodeError, KeyError):
            return "unknown"
    
    def _break_stale(self) -> bool:
        """Break a stale lock if the holder appears to have crashed.
        
        A lock is considered stale if:
        1. The holder.json is older than stale_threshold, OR
        2. The holder.json doesn't exist (incomplete lock), OR
        3. The holder PID is no longer running (POSIX only)
        
        Returns True if stale lock was broken.
        """
        try:
            if not os.path.exists(self.meta_path):
                # Lock dir exists but no metadata — likely crashed during acquire
                lock_age = time.time() - os.path.getmtime(self.lock_dir)
                if lock_age > self.stale_threshold:
                    self._force_break()
                    return True
                return False
            
            with open(self.meta_path) as f:
                meta = json.load(f)
            
            acquired_at = meta.get("acquired_at", 0)
            holder_pid = meta.get("pid")
            
            # Check age
            if time.time() - acquired_at > self.stale_threshold:
                logger.warning(
                    f"Breaking stale lock on {self.path} "
                    f"(held by pid={holder_pid} for {time.time() - acquired_at:.0f}s)"
                )
                self._force_break()
                return True
            
            # Check if holder PID is alive (POSIX only)
            if holder_pid and holder_pid != os.getpid():
                try:
                    os.kill(holder_pid, 0)  # Signal 0 = check existence
                except ProcessLookupError:
                    logger.warning(
                        f"Breaking orphaned lock on {self.path} "
                        f"(holder pid={holder_pid} no longer exists)"
                    )
                    self._force_break()
                    return True
                except (OSError, PermissionError):
                    pass  # Process exists but we can't signal it — not stale
            
            return False
        except (OSError, json.JSONDecodeError):
            return False
    
    def _force_break(self):
        """Force-break a lock by removing the lock directory."""
        try:
            if os.path.exists(self.meta_path):
                os.unlink(self.meta_path)
            os.rmdir(self.lock_dir)
        except OSError:
            pass
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, *exc):
        self.release()
        return False
    
    def __del__(self):
        """Safety net — release lock if holder is garbage collected."""
        if self._held:
            self.release()
