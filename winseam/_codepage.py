"""Which encodings this machine actually uses, and where each one applies.

Windows has more than one "default" at a time. The ANSI code page is what
``locale.getpreferredencoding(False)`` returns and what ``subprocess(text=True)``
decodes with; the console output code page is what console programs write. They
are routinely different -- cp1251 and cp866 on a Russian install, cp1252 and
cp850 on a western one -- so no single ``encoding=`` is correct for every child
of the same process.
"""
from __future__ import annotations

import locale
import sys
from typing import Optional

__all__ = ["ansi_encoding", "console_encoding", "is_windows"]


def is_windows() -> bool:
    return sys.platform == "win32"


def ansi_encoding() -> str:
    """The locale code page: what the standard library decodes text mode with."""
    return locale.getpreferredencoding(False) or "utf-8"


def console_encoding() -> Optional[str]:
    """The console output code page, or None off Windows / when it cannot be read.

    Read through ``GetConsoleOutputCP``, which reports the code page a console
    program writes in even when this process's own output is a pipe.
    """
    if not is_windows():
        return None
    try:
        import ctypes

        cp = int(ctypes.windll.kernel32.GetConsoleOutputCP())  # type: ignore[attr-defined]
    except Exception:
        return None
    if cp <= 0:
        return None
    if cp == 65001:
        return "utf-8"
    codec = "cp%d" % cp
    try:
        "".encode(codec)
    except LookupError:
        return None
    return codec
