"""Process-owned run leases, released by the OS when a worker exits."""
from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path


class RunLease:
    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor

    def close(self) -> None:
        descriptor, self.descriptor = self.descriptor, -1
        if descriptor < 0:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def try_run_lease(data_dir: Path, run_id: str) -> RunLease | None:
    directory = data_dir / ".run_locks"
    directory.mkdir(mode=0o700, exist_ok=True)
    filename = hashlib.sha256(run_id.encode()).hexdigest() + ".lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory / filename, flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return None
        raise
    return RunLease(descriptor)
