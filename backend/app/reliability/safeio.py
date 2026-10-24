"""Bounded host-owned JSON and file I/O. No application or evaluator imports."""
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
from uuid import uuid4


LIMIT = 2_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw, bound=LIMIT):
    if type(raw) is not bytes or not 0 < len(raw) <= bound:
        raise ValueError("Missing or oversized JSON")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def finite(text):
        result = float(text)
        if not math.isfinite(result):
            raise ValueError("Nonfinite JSON")
        return result
    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_float=finite,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid bounded JSON") from error
    if type(result) is not dict:
        raise ValueError("JSON object required")
    return result


class Files:
    """Caller authorizes root ancestors. Every descendant open rejects links."""
    def __init__(self, root):
        self.root = Path(root).absolute()

    @staticmethod
    def parts(path):
        if (type(path) is not str or not path or len(path.encode()) > 512
                or "\\" in path or "\x00" in path or PurePosixPath(path).is_absolute()
                or any(p in ("", ".", "..") for p in path.split("/"))):
            raise ValueError("Safe scoped path required")
        return PurePosixPath(path).parts

    def directory(self, parts=()):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = following
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, path, bound=LIMIT):
        parts = self.parts(path)
        directory = self.directory(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > bound:
                raise ValueError("Bounded regular file without aliases required")
            raw = stream.read(bound + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > bound or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("File changed during bounded read")
        return raw

    def write_new(self, path, raw):
        if type(raw) is not bytes or not 0 < len(raw) <= LIMIT:
            raise ValueError("Bounded bytes required")
        parts = self.parts(path)
        directory = self.directory(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o444)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)
        finally:
            os.close(directory)

    def index(self, value):
        raw = canonical(value) + b"\n"
        if len(raw) > LIMIT:
            raise ValueError("Oversized export index")
        directory = self.directory()
        temporary = f".index-{uuid4().hex}.tmp"
        try:
            try:
                old = os.stat("index.json", dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(old.st_mode) or old.st_nlink != 1:
                    raise ValueError("Index must be regular without aliases")
            except FileNotFoundError:
                pass
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o444)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, "index.json", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)
