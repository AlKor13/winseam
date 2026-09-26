"""The scanner: it must find the four defects, and stay quiet about correct code."""
import os

from winseam.audit import scan_path, scan_source

BAD = '''
import subprocess, shutil, json
from pathlib import Path

def go(path):
    out = subprocess.run(["git", "log"], capture_output=True, text=True).stdout
    proc = subprocess.Popen(["npm", "ls"], universal_newlines=True)
    data = json.load(open(path))
    body = Path(path).read_text()
    Path(path).write_text(body)
    shutil.rmtree(".cache")
    return out, proc, data, body
'''

GOOD = '''
import subprocess, shutil, json
from pathlib import Path
import winseam

def go(path):
    out = subprocess.run(["git", "log"], capture_output=True, text=True,
                         encoding="utf-8").stdout
    data = json.load(open(path, encoding="utf-8"))
    body = Path(path).read_text(encoding="utf-8")
    Path(path).write_text(body, encoding="utf-8")
    shutil.rmtree(".cache", ignore_errors=True)
    blob = open(path, "rb").read()
    winseam.rmtree(".cache")
    return out, data, body, blob
'''


def codes(source):
    return sorted(f.code for f in scan_source(source))


def test_finds_every_defect():
    found = codes(BAD)
    assert found.count("WS001") == 2      # text=True and universal_newlines=True
    assert found.count("WS002") == 1      # open() in text mode
    assert found.count("WS003") == 2      # read_text + write_text
    assert found.count("WS004") == 1      # rmtree


def test_correct_code_is_quiet():
    assert codes(GOOD) == []


def test_binary_mode_is_not_a_text_defect():
    assert codes('open("f", "rb").read()') == []
    assert codes('open("f", mode="rb").read()') == []


def test_text_false_is_not_flagged():
    assert codes('import subprocess\nsubprocess.run(["x"], text=False)') == []


def test_findings_carry_a_place_and_a_fix():
    finding = scan_source(BAD)[0]
    assert finding.line > 0
    assert finding.fix
    assert finding.as_dict()["code"] == finding.code


def test_a_file_that_does_not_parse_is_skipped():
    assert scan_source("def (:") == []


def test_scan_path_walks_a_tree_and_skips_noise(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(BAD, encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hook.py").write_text(BAD, encoding="utf-8")
    (tmp_path / "notes.txt").write_text(BAD, encoding="utf-8")

    findings = scan_path(str(tmp_path))
    assert findings
    assert {os.path.basename(f.path) for f in findings} == {"m.py"}


def test_scan_path_accepts_a_single_file(tmp_path):
    target = tmp_path / "m.py"
    target.write_text(BAD, encoding="utf-8")
    assert scan_path(str(target))
