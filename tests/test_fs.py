"""The filesystem seam: encodings, read-only files, and files someone still holds."""
import json
import os
import shutil
import stat

import pytest

from winseam import read_json, read_text, replace, rmtree, unlink, write_json, write_text
from winseam._codepage import is_windows

NON_ASCII = "Тест — café 😀"


def test_text_round_trip(tmp_path):
    target = tmp_path / "a.txt"
    write_text(target, NON_ASCII)
    assert read_text(target) == NON_ASCII


def test_written_files_are_utf8_without_a_bom(tmp_path):
    target = tmp_path / "a.txt"
    write_text(target, NON_ASCII)
    raw = target.read_bytes()
    assert raw == NON_ASCII.encode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_newlines_are_not_translated(tmp_path):
    target = tmp_path / "a.txt"
    write_text(target, "one\ntwo\n")
    assert target.read_bytes() == b"one\ntwo\n"


def test_a_bom_written_by_another_tool_is_read_away(tmp_path):
    target = tmp_path / "bom.txt"
    target.write_bytes(b"\xef\xbb\xbf" + NON_ASCII.encode("utf-8"))
    assert read_text(target) == NON_ASCII


def test_json_round_trip(tmp_path):
    target = tmp_path / "a.json"
    data = {"title": NON_ASCII, "n": 1}
    write_json(target, data)
    assert read_json(target) == data
    assert NON_ASCII in target.read_bytes().decode("utf-8")      # not \u-escaped


def test_read_text_reads_a_utf8_file_whatever_the_locale(tmp_path):
    """The failure that starts every one of these bug reports."""
    target = tmp_path / "a.json"
    target.write_bytes(json.dumps({"t": NON_ASCII}, ensure_ascii=False).encode("utf-8"))
    assert read_json(target)["t"] == NON_ASCII


# ----------------------------------------------------------------- rmtree
def _tree_with_read_only_file(root):
    root.mkdir()
    obj = root / "object"
    obj.write_text("x")
    os.chmod(obj, stat.S_IREAD)
    return obj


def test_rmtree_removes_read_only_files(tmp_path):
    root = tmp_path / "repo"
    _tree_with_read_only_file(root)
    rmtree(root)
    assert not root.exists()


@pytest.mark.skipif(not is_windows(), reason="POSIX deletes read-only files happily")
def test_the_standard_library_cannot(tmp_path):
    """Pins the defect: this is why every project writes an onerror handler."""
    root = tmp_path / "repo"
    obj = _tree_with_read_only_file(root)
    with pytest.raises(PermissionError):
        shutil.rmtree(root)
    os.chmod(obj, stat.S_IWRITE)          # leave the temp dir removable


def test_rmtree_missing_path(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError):
        rmtree(missing)
    rmtree(missing, ignore_errors=True)


def test_rmtree_nested(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "f.txt").write_text("x")
    os.chmod(deep / "f.txt", stat.S_IREAD)
    rmtree(tmp_path / "a")
    assert not (tmp_path / "a").exists()


# ----------------------------------------------------------------- replace / unlink
def test_replace_over_an_existing_read_only_file(tmp_path):
    src, dst = tmp_path / "new", tmp_path / "old"
    src.write_text("new")
    dst.write_text("old")
    os.chmod(dst, stat.S_IREAD)
    replace(src, dst)
    assert read_text(dst) == "new"
    assert not src.exists()


def test_unlink_a_read_only_file(tmp_path):
    target = tmp_path / "f"
    target.write_text("x")
    os.chmod(target, stat.S_IREAD)
    unlink(target)
    assert not target.exists()


def test_unlink_missing(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError):
        unlink(missing)
    unlink(missing, missing_ok=True)


def test_unlink_gives_up_on_a_handle_that_is_genuinely_held(tmp_path):
    """Retrying waits out a scanner; it must not hang on a real holder.

    On POSIX the unlink simply succeeds, which is the platform difference this
    package exists to make visible rather than hide.
    """
    target = tmp_path / "busy"
    target.write_text("x")
    handle = open(target)
    try:
        if is_windows():
            with pytest.raises(PermissionError):
                unlink(target, retries=1, delay=0.01)
        else:
            unlink(target)
            assert not target.exists()
    finally:
        handle.close()
