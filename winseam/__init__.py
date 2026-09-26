"""winseam -- make a Python tool behave the same on Windows as everywhere else.

Two seams, both measured rather than assumed:

* **Between processes.** A machine has more than one code page at a time. A
  Python child writes UTF-8, a console child writes the console code page
  (cp866 where the ANSI page is cp1251), and ``subprocess(text=True)`` decodes
  every one of them with the ANSI page. ``winseam.run`` decides per child and
  tells you which encoding answered.

* **At the filesystem.** Read-only files cannot be deleted (which is how Git
  stores its objects), an open handle blocks deletion and replacement, and text
  files open in the locale code page. ``winseam.read_text`` / ``rmtree`` /
  ``replace`` / ``unlink`` do the thing every project eventually writes by hand.

Off Windows every function is a thin wrapper with the same behaviour, so the
call site is written once.

    from winseam import run, read_text, rmtree

    result = run(["git", "status"])
    print(result.stdout, result.encoding)
"""
from ._codepage import ansi_encoding, console_encoding, is_windows
from ._fs import read_json, read_text, replace, rmtree, unlink, write_json, write_text
from ._proc import decode, decoding_ladder, run

__version__ = "0.1.0"

__all__ = [
    "run", "decode", "decoding_ladder",
    "read_text", "write_text", "read_json", "write_json",
    "rmtree", "replace", "unlink",
    "ansi_encoding", "console_encoding", "is_windows",
    "__version__",
]
