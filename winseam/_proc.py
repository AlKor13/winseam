"""Run a child process and get text back, whoever the child is.

``subprocess.run(..., text=True)`` decodes with the ANSI code page. A Python
child writes UTF-8 (and from 3.15 always will), a console program writes the
console code page, and a program you configured writes whatever you asked for --
so one decoder for all of them is wrong on Windows by construction. This module
picks per child, and reports which encoding answered instead of guessing
silently.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from ._codepage import ansi_encoding, console_encoding, is_windows

__all__ = ["run", "decode", "decoding_ladder"]

# PowerShell 5.1 writes a UTF-8 BOM into the pipe it hands a child, and several
# Windows tools prefix their own output the same way. It is never part of the text.
_BOMS = ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))

_PYTHON_EXES = ("python", "python3", "pythonw", "py")


def _is_python_child(args: Any) -> bool:
    """Whether the child is a Python interpreter, whose encoding we can dictate."""
    if isinstance(args, str):
        parts = args.split()
        first = parts[0] if parts else ""
    elif isinstance(args, (list, tuple)) and args:
        first = str(args[0])
    else:
        return False
    name = os.path.basename(first).lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name in _PYTHON_EXES or name.startswith("python")


def decoding_ladder(python_child: bool = False) -> List[str]:
    """The encodings tried, in order, when the caller names none.

    UTF-8 first: it is self-validating, so a strict decode that succeeds is
    almost certainly right, and it is what a configured child and every modern
    tool emits. The console code page comes next, because that is what a console
    program writes, and the ANSI code page last.

    Single-byte code pages are not self-validating -- cp866 bytes decode
    "successfully" as cp1251 and give mojibake -- so below UTF-8 this is a prior,
    not a detector. That is exactly why the encoding used is handed back to the
    caller rather than kept secret.
    """
    ladder = ["utf-8"]
    if not python_child:
        for candidate in (console_encoding(), ansi_encoding()):
            if candidate and candidate not in ladder:
                ladder.append(candidate)
    return ladder


def _strip_bom(data: bytes) -> Tuple[bytes, Optional[str]]:
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return data[len(bom):], enc
    return data, None


def decode(data: bytes, encoding: Optional[str] = None, errors: str = "strict",
           python_child: bool = False) -> Tuple[str, str]:
    """Decode child output; return the text and the encoding that produced it."""
    if not data:
        return "", encoding or "utf-8"
    data, bom_encoding = _strip_bom(data)
    if encoding is not None:
        return data.decode(encoding, errors), encoding
    if bom_encoding is not None:
        try:
            return data.decode(bom_encoding), bom_encoding
        except UnicodeDecodeError:
            pass
    ladder = decoding_ladder(python_child)
    for candidate in ladder:
        try:
            return data.decode(candidate), candidate
        except (UnicodeDecodeError, LookupError):
            continue
    # Nothing decoded strictly. Answer with the most likely code page rather than
    # raising, and mark the text lossy so a caller can tell it apart from a clean read.
    fallback = ladder[-1]
    return data.decode(fallback, "replace"), fallback + "/replace"


def run(args: Any, encoding: Optional[str] = None, errors: str = "strict",
        input: Optional[Union[str, bytes]] = None,
        env: Optional[Mapping[str, str]] = None,
        capture_output: bool = True, check: bool = False,
        **kwargs: Any) -> subprocess.CompletedProcess:
    """Like ``subprocess.run(..., text=True)``, but correct on Windows.

    Returns a ``CompletedProcess`` whose ``stdout``/``stderr`` are ``str``, with
    two attributes the standard library has no room for: ``encodings`` (per
    stream) and ``encoding`` (stdout's).

    A Python child is *configured* rather than guessed at: ``PYTHONUTF8`` and
    ``PYTHONIOENCODING`` are set for it unless the caller set them already, so
    its output is UTF-8 on every Python version and under every locale.
    """
    for banned in ("text", "universal_newlines"):
        if banned in kwargs:
            raise TypeError(
                "winseam.run always returns text and decodes it itself; drop %r "
                "(pass encoding=... to force one)" % banned
            )

    python_child = _is_python_child(args)
    child_env = dict(os.environ if env is None else env)
    if python_child and is_windows():
        child_env.setdefault("PYTHONUTF8", "1")
        child_env.setdefault("PYTHONIOENCODING", "utf-8")

    stdin_bytes = None  # type: Optional[bytes]
    if input is not None:
        if isinstance(input, bytes):
            stdin_bytes = input
        else:
            # The same seam in the other direction: a console child reads the
            # console code page, a Python child reads what we just configured.
            # No BOM is written either way -- it is not part of the text, and a
            # child that parses its own first line chokes on one.
            stdin_encoding = encoding or ("utf-8" if python_child else
                                          (console_encoding() or ansi_encoding()))
            stdin_bytes = input.encode(stdin_encoding, errors)

    completed = subprocess.run(
        args, input=stdin_bytes, env=child_env, capture_output=capture_output, **kwargs
    )

    encodings = {}  # type: Dict[str, Optional[str]]
    decoded = {}  # type: Dict[str, Optional[str]]
    for stream in ("stdout", "stderr"):
        raw = getattr(completed, stream, None)
        if raw is None:
            decoded[stream], encodings[stream] = None, None
            continue
        text, used = decode(raw, encoding=encoding, errors=errors, python_child=python_child)
        decoded[stream], encodings[stream] = text, used

    result = subprocess.CompletedProcess(
        completed.args, completed.returncode, decoded["stdout"], decoded["stderr"]
    )
    result.encodings = encodings  # type: ignore[attr-defined]
    result.encoding = encodings["stdout"] or encodings["stderr"]  # type: ignore[attr-defined]
    if check:
        result.check_returncode()
    return result
