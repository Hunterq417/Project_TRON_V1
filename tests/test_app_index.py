# tests/test_app_index.py
from pathlib import Path
from unittest.mock import MagicMock

import app_index


def test_build_index_scans_startmenu_and_media_folders(tmp_path):
    startmenu = tmp_path / "startmenu"
    (startmenu / "sub").mkdir(parents=True)
    (startmenu / "Notepad.lnk").write_text("")
    (startmenu / "sub" / "Chess Titans.lnk").write_text("")

    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    (home / "Pictures" / "dune poster.jpg").write_text("")
    (home / "Videos").mkdir(parents=True)

    index = app_index.build_index(startmenu_dirs=[startmenu], home=home)

    assert index["notepad"] == startmenu / "Notepad.lnk"
    assert index["chess titans"] == startmenu / "sub" / "Chess Titans.lnk"
    assert index["dune poster"] == home / "Pictures" / "dune poster.jpg"


def test_build_index_skips_missing_directories(tmp_path):
    index = app_index.build_index(startmenu_dirs=[tmp_path / "nope"], home=tmp_path / "also-nope")
    assert index == {}


def test_resolve_fuzzy_matches_closest_name():
    index = {
        "notepad": Path("C:/x/notepad.lnk"),
        "chrome": Path("C:/x/chrome.lnk"),
    }

    assert app_index.resolve("note pad", index) == Path("C:/x/notepad.lnk")
    assert app_index.resolve("chrom", index) == Path("C:/x/chrome.lnk")


def test_resolve_returns_none_when_nothing_close():
    index = {"notepad": Path("C:/x/notepad.lnk")}
    assert app_index.resolve("completely unrelated query", index) is None


def test_resolve_returns_none_for_empty_index():
    assert app_index.resolve("anything", {}) is None


def test_resolve_rejects_weak_matches_below_the_stricter_cutoff():
    # "notepad" vs "onenote" scores ~0.57 — plausible-looking but wrong, and
    # below the 0.65 cutoff. A wrong match is worse than an honest "not found".
    index = {"onenote": Path("C:/x/OneNote.lnk")}
    assert app_index.resolve("notepad", index) is None


def test_launch_calls_os_startfile(monkeypatch):
    fake_startfile = MagicMock()
    monkeypatch.setattr(app_index.os, "startfile", fake_startfile, raising=False)

    app_index.launch(Path("C:/x/notepad.lnk"))

    fake_startfile.assert_called_once_with("C:\\x\\notepad.lnk")


def test_try_direct_launch_returns_true_on_success(monkeypatch):
    fake_startfile = MagicMock()
    monkeypatch.setattr(app_index.os, "startfile", fake_startfile, raising=False)

    assert app_index.try_direct_launch("notepad") is True
    fake_startfile.assert_called_once_with("notepad")


def test_try_direct_launch_returns_false_when_windows_cant_resolve_it(monkeypatch):
    fake_startfile = MagicMock(side_effect=OSError("not found"))
    monkeypatch.setattr(app_index.os, "startfile", fake_startfile, raising=False)

    assert app_index.try_direct_launch("not-a-real-command-xyz") is False
