"""Owner-only runtime paths, atomic files and single-instance socket ownership."""

from __future__ import annotations

import errno
import fcntl
import os
import secrets
import socket
import stat
from pathlib import Path


class RuntimeSafetyError(ValueError):
    """The configured local runtime cannot be used safely."""


def private_directory(path: Path) -> None:
    """Create a private directory, rejecting symlinks and unsafe ownership."""
    path = path.absolute()
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise RuntimeSafetyError("Runtime paths must not contain symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeSafetyError("Runtime directory must be owned by the current user with mode 0700")


def private_open(path: Path, flags: int) -> int:
    """Open an owner-only regular file without following a final symlink."""
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        os.close(fd)
        raise RuntimeSafetyError("Runtime file must be a private, singly linked regular file")
    return fd


def sync_directory(path: Path) -> None:
    """Persist a directory entry change before acknowledging it."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    """Replace a private file and fsync both its bytes and directory entry."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = private_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if path.is_symlink():
            raise RuntimeSafetyError("Refusing to replace a runtime symlink")
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_token(token_file: Path) -> str:
    """Read or initialise a private bearer token under a creation lock."""
    private_directory(token_file.parent)
    lock_fd = private_open(token_file.with_name(token_file.name + ".lock"), os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            fd = private_open(token_file, os.O_RDONLY)
        except FileNotFoundError:
            token = secrets.token_urlsafe(32)
            fd = private_open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "wb") as output:
                output.write(token.encode("ascii"))
                output.flush()
                os.fsync(output.fileno())
            sync_directory(token_file.parent)
            return token
        with os.fdopen(fd, "rb") as source:
            raw = source.read(4097)
        token = raw.decode("ascii").strip()
        if len(raw) > 4096 or not token or any(c.isspace() for c in token):
            raise RuntimeSafetyError("Invalid bridge token file")
        return token
    finally:
        os.close(lock_fd)


class SocketLease:
    """Own a runtime lock and remove only the socket created by this instance."""

    def __init__(self, path: Path) -> None:
        """Reserve an endpoint without stealing a listening instance."""
        private_directory(path.parent)
        self.path = path
        self.inode: int | None = None
        self.fd = private_open(path.parent / "bridge.lock", os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._remove_stale()
        except BaseException:
            os.close(self.fd)
            self.fd = -1
            raise

    def _remove_stale(self) -> None:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeSafetyError("Existing endpoint is not an owned private socket")
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(0.2)
            try:
                probe.connect(str(self.path))
            except OSError as exc:
                if exc.errno != errno.ECONNREFUSED:
                    raise RuntimeSafetyError("Cannot establish that the existing socket is stale") from exc
            else:
                raise RuntimeSafetyError("A bridge is already listening")
        if self.path.lstat().st_ino != info.st_ino:
            raise RuntimeSafetyError("Endpoint changed during startup")
        self.path.unlink()

    def bound(self) -> None:
        """Record the socket inode after binding with owner-only permissions."""
        os.chmod(self.path, 0o600)
        self.inode = self.path.lstat().st_ino

    def close(self) -> None:
        """Release this instance's socket and lock without deleting other files."""
        try:
            if self.inode is not None:
                try:
                    info = self.path.lstat()
                    if stat.S_ISSOCK(info.st_mode) and info.st_ino == self.inode:
                        self.path.unlink()
                except FileNotFoundError:
                    pass
        finally:
            if self.fd >= 0:
                os.close(self.fd)
                self.fd = -1
