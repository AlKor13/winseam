"""File operations that behave the same on Windows as they do everywhere else.

Every function here is a thin wrapper that stays out of the way on POSIX. The
differences it papers over are Windows semantics, not Python bugs:

* text files open in the locale code page, so a UTF-8 file written by any other
  tool raises ``UnicodeDecodeError`` on a machine whose ANSI page is not UTF-8;
* a read-only file cannot be deleted, and that is how Git stores every object in
  ``.git``, so ``shutil.rmtree`` on a clone raises ``PermissionError``;
* an open handle blocks deletion and replacement, and the handle is often not
  yours -- an indexer or a virus scanner opens files moments after they appear,
  which makes the failure intermittent and unreproducible on the machine that
  reports it.
"""
from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import time
from typing import Any, Callable, Optional, Union

__all__ = ["read_text", "write_text", "read_json", "write_json",
           "rmtree", "replace", "unlink"]

PathLike = Union[str, "os.PathLike[str]"]

# Retries exist for handles that are about to go away (an indexer, a scanner, a
# just-exited child). A handle that is genuinely held will still fail, and it
# should: the alternative is hanging.
_RETRIES = 5
_DELAY = 0.05


def read_text(path: PathLike, encoding: str = "utf-8-sig", errors: str = "strict") -> str:
    """Read a text file as UTF-8, tolerating a BOM.

    ``utf-8-sig`` is the default because Windows tools write one -- PowerShell's
    ``Out-File`` and ``Set-Content``, Notepad, many exporters -- and a leading
    ``\\ufeff`` is not part of anybody's data. It reads plain UTF-8 unchanged.
    """
    with open(path, "r", encoding=encoding, errors=errors, newline="") as fh:
        return fh.read()


def write_text(path: PathLike, text: str, encoding: str = "utf-8",
               errors: str = "strict", newline: str = "\n") -> None:
    """Write UTF-8 without a BOM and with the newline you asked for.

    The explicit ``newline`` matters: text mode translates ``\\n`` to ``\\r\\n``
    on Windows, so a file written by the same code is byte-different per
    platform, which shows up as a whole-file diff in review.
    """
    with open(path, "w", encoding=encoding, errors=errors, newline=newline) as fh:
        fh.write(text)


def read_json(path: PathLike, **kwargs: Any) -> Any:
    """``json.load`` that does not depend on the machine's code page."""
    return json.loads(read_text(path), **kwargs)


def write_json(path: PathLike, data: Any, *, indent: Optional[int] = 2,
               ensure_ascii: bool = False, **kwargs: Any) -> None:
    """``json.dump`` that writes UTF-8 without a BOM, non-ASCII text intact."""
    write_text(path, json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, **kwargs))


def _make_writable(path: PathLike) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _retry(action: Callable[[], None], retries: int, delay: float) -> None:
    last = None
    for attempt in range(retries + 1):
        try:
            action()
            return
        except PermissionError as exc:          # WinError 5 / 32
            last = exc
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EBUSY):
                raise
            last = exc
        if attempt < retries:
            time.sleep(delay * (attempt + 1))
    assert last is not None
    raise last


def rmtree(path: PathLike, *, ignore_errors: bool = False,
           retries: int = _RETRIES, delay: float = _DELAY) -> None:
    """``shutil.rmtree`` that can delete a Git clone.

    Read-only files are made writable and retried, which is what every project
    ends up writing by hand once it tries to remove a directory containing
    ``.git`` on Windows.
    """
    def on_error(func: Callable[..., Any], failing: str, exc_info: Any) -> None:
        _make_writable(failing)
        func(failing)

    def attempt() -> None:
        # onexc replaced onerror in 3.12; passing the old name still works there
        # but warns, so pick by capability rather than by version number.
        try:
            shutil.rmtree(path, onexc=lambda func, p, exc: on_error(func, p, exc))  # type: ignore[call-arg]
        except TypeError:
            shutil.rmtree(path, onerror=on_error)

    try:
        _retry(attempt, retries, delay)
    except FileNotFoundError:
        if not ignore_errors:
            raise
    except OSError:
        if not ignore_errors:
            raise


def replace(src: PathLike, dst: PathLike, *, retries: int = _RETRIES,
            delay: float = _DELAY) -> None:
    """``os.replace`` that survives a scanner holding the destination for a moment."""
    def attempt() -> None:
        if os.path.exists(dst):
            _make_writable(dst)
        os.replace(src, dst)

    _retry(attempt, retries, delay)


def unlink(path: PathLike, *, missing_ok: bool = False, retries: int = _RETRIES,
           delay: float = _DELAY) -> None:
    """``os.remove`` that clears the read-only bit and waits out a transient handle."""
    def attempt() -> None:
        try:
            os.remove(path)
        except PermissionError:
            _make_writable(path)
            os.remove(path)

    try:
        _retry(attempt, retries, delay)
    except FileNotFoundError:
        if not missing_ok:
            raise
