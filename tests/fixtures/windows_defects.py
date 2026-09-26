"""Deliberately wrong, as a fixture: every line here is a defect the audit must find.

Kept as a real file rather than a string so the pre-commit hook, the GitHub Action
and the scanner are all exercised against the same thing. Nothing imports it.
"""
import json
import shutil
import subprocess
from pathlib import Path


def collect(path):
    log = subprocess.run(["git", "log"], capture_output=True, text=True).stdout      # WS001
    proc = subprocess.Popen(["npm", "ls"], universal_newlines=True)                  # WS001
    config = json.load(open(path))                                                   # WS002
    body = Path(path).read_text()                                                     # WS003
    Path(path).write_text(body)                                                       # WS003
    shutil.rmtree(".cache")                                                           # WS004
    return log, proc, config, body
