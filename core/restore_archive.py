"""Bounded extraction of untrusted legacy backup archives into a fresh directory."""

import os
import re
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path

MAX_ARCHIVE_BYTES = 64 * 1024**3
MAX_ARCHIVE_MEMBERS = 10000
_CHUNK_BYTES = 1024 * 1024
_DEVICE_NAME = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)


class UnsafeRestoreArchive(ValueError):
    pass


def _member_path(root, name):
    parts = name.rstrip('/').split('/')
    if (not name or '\\' in name or '\x00' in name
            or any(not part or part in ('.', '..') or ':' in part
                   or part.endswith(('.', ' ')) or _DEVICE_NAME.match(part)
                   for part in parts)):
        raise UnsafeRestoreArchive("Archive contains an unsafe member path.")
    target = root.joinpath(*parts)
    if os.path.commonpath((str(root), str(target.resolve()))) != str(root):
        raise UnsafeRestoreArchive("Archive member escapes the extraction directory.")
    return target


def extract_backup_archive(source, destination, *, max_bytes=MAX_ARCHIVE_BYTES,
                           max_members=MAX_ARCHIVE_MEMBERS):
    """Extract only regular files/directories; never restore archive links or modes."""
    root = Path(destination).resolve()
    if not root.is_dir() or any(root.iterdir()):
        raise UnsafeRestoreArchive("Extraction requires a fresh, empty directory.")
    byte_limit = min(max_bytes, max(0, shutil.disk_usage(root).free - 128 * 1024**2))

    seen = set()
    declared_bytes = 0
    written_bytes = 0
    backup = None

    def register(name, size):
        nonlocal declared_bytes
        target = _member_path(root, name)
        key = str(target).casefold()
        if key in seen or len(seen) >= max_members:
            raise UnsafeRestoreArchive("Archive has duplicate paths or too many members.")
        seen.add(key)
        declared_bytes += size
        if size < 0 or declared_bytes > byte_limit:
            raise UnsafeRestoreArchive("Archive exceeds the extraction size limit.")
        return target

    def write_member(target, stream, expected_size):
        nonlocal written_bytes, backup
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with stream, target.open('xb') as output:
            while True:
                chunk = stream.read(_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                written_bytes += len(chunk)
                if size > expected_size or written_bytes > byte_limit:
                    raise UnsafeRestoreArchive("Archive exceeds the extraction size limit.")
                output.write(chunk)
        if size != expected_size:
            raise UnsafeRestoreArchive("Archive member size does not match its metadata.")
        if backup is None and target.suffix.lower() == '.bak':
            backup = str(target)

    if str(source).lower().endswith('.zip'):
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > max_members:
                raise UnsafeRestoreArchive("Archive has too many members.")
            pending = []
            for member in members:
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise UnsafeRestoreArchive("Archive links and special files are forbidden.")
                target = register(member.filename, member.file_size)
                pending.append((member, target))
            for member, target in pending:
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    write_member(target, archive.open(member), member.file_size)
    else:
        with tarfile.open(source, mode='r:gz') as archive:
            pending = []
            for member in archive:
                if not (member.isfile() or member.isdir()) or member.issparse():
                    raise UnsafeRestoreArchive("Archive links and special files are forbidden.")
                target = register(member.name, member.size)
                pending.append((member, target))
            for member, target in pending:
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise UnsafeRestoreArchive("Archive member cannot be read.")
                    write_member(target, stream, member.size)

    if backup is None:
        raise UnsafeRestoreArchive("Archive contains no .bak file.")
    return backup
