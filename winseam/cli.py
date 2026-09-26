"""``winseam audit`` and ``winseam doctor``.

``doctor`` exists because the first question on any Windows bug report is "which
code pages does that machine have", and nobody can answer it from memory. Its
output is meant to be pasted into an issue.
"""
from __future__ import annotations

import argparse
import json
import locale
import sys
from collections import Counter
from typing import List, Optional, Sequence

from ._codepage import ansi_encoding, console_encoding, is_windows
from ._proc import decoding_ladder
from .audit import Finding, scan_path


def _print_report(findings: List[Finding], root: str) -> None:
    if not findings:
        print("winseam: nothing to report in %s" % root)
        return

    by_file: dict = {}
    for finding in findings:
        by_file.setdefault(finding.path, []).append(finding)

    for path in sorted(by_file):
        print("\n%s" % path)
        for finding in sorted(by_file[path], key=lambda f: f.line):
            print("  %4d  %s  %s" % (finding.line, finding.code, finding.message))
            print("        fix: %s" % finding.fix)

    counts = Counter(f.code for f in findings)
    print("\n%d finding%s in %d file%s"
          % (len(findings), "" if len(findings) == 1 else "s",
             len(by_file), "" if len(by_file) == 1 else "s"))
    for code, count in sorted(counts.items()):
        print("  %s  %d" % (code, count))


def _doctor() -> int:
    console = console_encoding()
    print("winseam doctor")
    print("  platform            : %s" % sys.platform)
    print("  python              : %s" % sys.version.split()[0])
    print("  locale code page    : %s   (what subprocess text=True decodes with)"
          % ansi_encoding())
    print("  console code page   : %s   (what a console child writes)"
          % (console or "n/a"))
    print("  filesystem encoding : %s" % sys.getfilesystemencoding())
    print("  stdout encoding     : %s" % (sys.stdout.encoding or "?"))
    print("  locale              : %s" % (locale.setlocale(locale.LC_CTYPE) or "?"))
    print("  decoding ladder     : %s" % ", ".join(decoding_ladder()))
    if is_windows() and console and console != ansi_encoding():
        print("\n  Two code pages are in force at once, which is the usual case: a child")
        print("  writing %s is decoded as %s by the standard library." % (console, ansi_encoding()))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="winseam",
        description="Find and fix the places a Python tool misbehaves on Windows.")
    sub = parser.add_subparsers(dest="command")

    audit = sub.add_parser("audit", help="scan paths for Windows text and filesystem defects")
    # Several paths, because pre-commit hands its hooks one argument per changed file.
    audit.add_argument("paths", nargs="*", default=["."], metavar="PATH")
    audit.add_argument("--json", action="store_true", help="machine-readable output")
    audit.add_argument("--exit-zero", action="store_true",
                       help="always exit 0, for a non-blocking CI step")

    sub.add_parser("doctor", help="print this machine's code pages, for a bug report")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command != "audit":
        parser.print_help()
        return 2

    paths = args.paths or ["."]
    findings = [f for path in paths for f in scan_path(path)]
    if args.json:
        print(json.dumps([f.as_dict() for f in findings], indent=2, ensure_ascii=False))
    else:
        _print_report(findings, ", ".join(paths))
    if args.exit_zero:
        return 0
    return 1 if findings else 0


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
