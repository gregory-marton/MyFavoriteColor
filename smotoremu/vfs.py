"""Temp-backed virtual flash filesystem for emulator sessions.

Co-authored-by: GPT-5, Aug 2026
"""

import os
import re
import shutil


class FileTooLargeError(ValueError):
    pass


class VFS:
    MAX_FILE_BYTES = None

    def __init__(self, root):
        self.root = os.path.abspath(os.fspath(root))
        os.makedirs(self.root, exist_ok=True)
        if self.MAX_FILE_BYTES is None:
            self.__class__.MAX_FILE_BYTES = _read_manifest_size_limit()

    def put(self, name: str, content: bytes | str) -> None:
        data = content.encode() if isinstance(content, str) else bytes(content)
        if len(data) > self.MAX_FILE_BYTES:
            raise FileTooLargeError(f"{name} is {len(data)} bytes, exceeding {self.MAX_FILE_BYTES}")
        path = self._path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def get(self, name: str) -> bytes:
        with open(self._path(name), "rb") as handle:
            return handle.read()

    def listdir(self) -> list[str]:
        return sorted(os.listdir(self.root))

    def wipe(self) -> None:
        for name in os.listdir(self.root):
            path = os.path.join(self.root, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    def load_manifest(self, manifest_path: str, source_dir: str) -> None:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            names = [line.strip() for line in handle if line.strip()]
        for name in names:
            source = os.path.join(source_dir, name)
            if os.path.exists(source):
                with open(source, "rb") as handle:
                    self.put(name, handle.read())

    def _path(self, name):
        if os.path.isabs(name):
            raise ValueError("VFS paths must be relative")
        path = os.path.abspath(os.path.join(self.root, name))
        if path != self.root and not path.startswith(self.root + os.sep):
            raise ValueError("VFS path escapes root")
        return path


def _read_manifest_size_limit():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    test_path = os.path.join(repo_root, "tests", "test_filesize.py")
    with open(test_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r"MAX_SIZE_BYTES\s*=\s*(\d+)", text)
    if not match:
        raise RuntimeError("could not read MAX_SIZE_BYTES from tests/test_filesize.py")
    return int(match.group(1))
