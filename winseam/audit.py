"""Find the places in a codebase that will misbehave on Windows.

A static pass, so it runs anywhere -- on Linux CI, on a machine whose code page
is UTF-8, on a project you do not own. It reports the three constructs that
account for nearly every Windows text bug in Python tooling, and nothing else:
the goal is a number a maintainer can act on, not a wall of style advice.
"""
from __future__ import annotations

import ast
import os
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["Finding", "scan_source", "scan_path"]

_SUBPROCESS_CALLS = {"run", "Popen", "check_output", "call", "check_call", "getoutput"}


class Finding:
    """One place worth changing, with the line and the fix."""

    __slots__ = ("path", "line", "col", "code", "message", "fix")

    def __init__(self, path: str, line: int, col: int, code: str, message: str, fix: str):
        self.path, self.line, self.col = path, line, col
        self.code, self.message, self.fix = code, message, fix

    def as_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "line": self.line, "column": self.col,
                "code": self.code, "message": self.message, "fix": self.fix}

    def __repr__(self) -> str:      # pragma: no cover - debugging aid
        return "Finding(%s:%d %s)" % (self.path, self.line, self.code)


def _kwarg(node: ast.Call, name: str) -> Optional[ast.keyword]:
    for kw in node.keywords:
        if kw.arg == name:
            return kw
    return None


def _is_truthy(kw: ast.keyword) -> bool:
    return isinstance(kw.value, ast.Constant) and bool(kw.value.value)


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = func.value
        if isinstance(owner, ast.Name):
            return "%s.%s" % (owner.id, func.attr)
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _mode_is_binary(node: ast.Call) -> bool:
    mode = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    kw = _kwarg(node, "mode")
    if kw is not None and isinstance(kw.value, ast.Constant):
        mode = kw.value.value
    return isinstance(mode, str) and "b" in mode


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.findings: List[Finding] = []

    def _add(self, node: ast.AST, code: str, message: str, fix: str) -> None:
        self.findings.append(
            Finding(self.path, getattr(node, "lineno", 0), getattr(node, "col_offset", 0),
                    code, message, fix))

    def visit_Call(self, node: ast.Call) -> None:
        name = _callee_name(node)
        tail = name.rsplit(".", 1)[-1]

        # Calls into this package are the fix, not the defect.
        if name.startswith("winseam."):
            self.generic_visit(node)
            return

        # WS001 -- text output decoded with the ANSI code page
        if tail in _SUBPROCESS_CALLS and ("subprocess" in name or tail in ("run", "Popen")):
            texty = _kwarg(node, "text") or _kwarg(node, "universal_newlines")
            if texty is not None and _is_truthy(texty) and _kwarg(node, "encoding") is None:
                self._add(node, "WS001",
                          "%s(text=True) without encoding= decodes the child with the ANSI "
                          "code page; a UTF-8 child is mojibake and a console child is worse" % name,
                          "winseam.run(...), or pass encoding= explicitly")

        # WS002 -- text file opened in the locale code page
        if tail == "open" and name in ("open", "io.open", "codecs.open"):
            if not _mode_is_binary(node) and _kwarg(node, "encoding") is None:
                self._add(node, "WS002",
                          "open() in text mode without encoding= reads the locale code page, "
                          "so a UTF-8 file raises UnicodeDecodeError off a UTF-8 machine",
                          'winseam.read_text(path), or open(..., encoding="utf-8")')

        # WS003 -- Path.read_text / write_text with the same defect
        if tail in ("read_text", "write_text") and isinstance(node.func, ast.Attribute):
            if _kwarg(node, "encoding") is None:
                self._add(node, "WS003",
                          ".%s() without encoding= uses the locale code page" % tail,
                          "winseam.read_text / winseam.write_text")

        # WS004 -- rmtree that cannot delete a read-only file, which is how Git stores objects
        if tail == "rmtree" and name in ("rmtree", "shutil.rmtree"):
            if (_kwarg(node, "onexc") is None and _kwarg(node, "onerror") is None
                    and _kwarg(node, "ignore_errors") is None):
                self._add(node, "WS004",
                          "shutil.rmtree() without onexc= fails with PermissionError on "
                          "read-only files, including every object in a .git directory",
                          "winseam.rmtree(path)")

        self.generic_visit(node)


def scan_source(source: str, path: str = "<string>") -> List[Finding]:
    """Findings for one module's source. A file that does not parse yields none."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _Visitor(path)
    visitor.visit(tree)
    return visitor.findings


_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox",
              ".mypy_cache", ".pytest_cache", "build", "dist", ".eggs"}


def _python_files(root: str) -> Iterable[str]:
    if os.path.isfile(root):
        yield root
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.endswith(".egg-info")]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(base, name)


def scan_path(root: str) -> List[Finding]:
    """Findings for every Python file under `root`, in a stable order."""
    findings: List[Finding] = []
    for path in sorted(_python_files(root)):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        findings.extend(scan_source(source, path))
    return findings
