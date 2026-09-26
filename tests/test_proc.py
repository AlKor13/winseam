"""The process seam: what comes back from a child, and in which encoding."""
import subprocess
import sys

import pytest

from winseam import decode, decoding_ladder, run
from winseam._codepage import ansi_encoding, console_encoding, is_windows

NON_ASCII = "Тест — café"


def test_python_child_round_trips_non_ascii():
    result = run([sys.executable, "-c", "print(%r)" % NON_ASCII])
    assert result.stdout.strip() == NON_ASCII
    assert result.encoding == "utf-8"
    assert result.returncode == 0


def test_result_is_a_completed_process():
    result = run([sys.executable, "-c", "print(1)"])
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.stderr == ""
    assert set(result.encodings) == {"stdout", "stderr"}


def test_explicit_encoding_wins():
    cyrillic = "Тест — файл"                 # every character exists in cp1251
    payload = cyrillic.encode("cp1251")
    code = "import sys;sys.stdout.buffer.write(%r)" % payload
    result = run([sys.executable, "-c", code], encoding="cp1251")
    assert result.stdout == cyrillic
    assert result.encoding == "cp1251"


def test_text_kwarg_is_refused():
    with pytest.raises(TypeError) as excinfo:
        run([sys.executable, "-c", "pass"], text=True)
    assert "winseam.run" in str(excinfo.value)


def test_str_input_reaches_a_python_child_intact():
    code = "import sys;print(sys.stdin.read().strip())"
    result = run([sys.executable, "-c", code], input=NON_ASCII)
    assert result.stdout.strip() == NON_ASCII


def test_bytes_input_is_passed_through():
    code = "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"
    result = run([sys.executable, "-c", code], input=NON_ASCII.encode("utf-8"))
    assert result.stdout == NON_ASCII


def test_check_raises_on_failure():
    with pytest.raises(subprocess.CalledProcessError):
        run([sys.executable, "-c", "raise SystemExit(3)"], check=True)


# ----------------------------------------------------------------- decode()
def test_decode_empty():
    assert decode(b"") == ("", "utf-8")


def test_decode_strips_a_utf8_bom():
    # PowerShell 5.1 prefixes the pipe it hands a child with one, and the BOM is
    # not part of anybody's text.
    text, encoding = decode("﻿".encode("utf-8") + NON_ASCII.encode("utf-8"))
    assert text == NON_ASCII
    assert encoding == "utf-8"


def test_decode_prefers_utf8():
    text, encoding = decode(NON_ASCII.encode("utf-8"))
    assert (text, encoding) == (NON_ASCII, "utf-8")


def test_decode_falls_back_without_raising():
    # 0x81 is undefined in cp1252 and invalid UTF-8: whatever the machine is,
    # the caller gets text and an honest label rather than an exception.
    text, encoding = decode(b"\x81\x81\x81")
    assert isinstance(text, str)
    assert encoding


def test_ladder_for_a_python_child_is_utf8_only():
    assert decoding_ladder(python_child=True) == ["utf-8"]


def test_ladder_starts_with_utf8():
    assert decoding_ladder()[0] == "utf-8"


# ----------------------------------------------------------------- Windows only
@pytest.mark.skipif(not is_windows(), reason="the seam only exists on Windows")
def test_console_child_is_decoded_with_the_console_code_page():
    console = console_encoding()
    if console is None:
        pytest.skip("no console code page available")
    char = next((c for c in "éäüТб" if _encodable(c, console)), None)
    if char is None:
        pytest.skip("console code page %s holds none of the probe characters" % console)

    result = run(["cmd", "/c", "echo %s" % char])
    assert result.stdout.strip() == char, (
        "expected the console code page %s, got %r via %s"
        % (console, result.stdout, result.encoding))


@pytest.mark.skipif(not is_windows(), reason="the seam only exists on Windows")
def test_the_standard_library_gets_this_wrong():
    """The defect this package exists for, pinned so it cannot quietly change.

    Skips rather than fails when the machine has one code page everywhere (an
    en-US box with UTF-8 enabled), because then there is no seam to get wrong.
    """
    console = console_encoding()
    if console is None or console == ansi_encoding():
        pytest.skip("this machine has a single code page, so nothing can disagree")
    char = next((c for c in "éäüТб" if _encodable(c, console)), None)
    if char is None or _same_bytes(char, console, ansi_encoding()):
        pytest.skip("no probe character distinguishes %s from %s" % (console, ansi_encoding()))

    naive = subprocess.run(["cmd", "/c", "echo %s" % char],
                           capture_output=True, text=True).stdout.strip()
    ours = run(["cmd", "/c", "echo %s" % char]).stdout.strip()
    assert ours == char
    assert naive != char, "the standard library agreed for once; the seam may have moved"


def _encodable(char, encoding):
    try:
        char.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _same_bytes(char, left, right):
    try:
        return char.encode(left) == char.encode(right)
    except (UnicodeEncodeError, LookupError):
        return False
