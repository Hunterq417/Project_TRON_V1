# tests/test_app_index.py
from pathlib import Path
from unittest.mock import MagicMock

import app_index

# Captured at import, before the autouse fixture that blocks real launching can
# replace them. These three tests are the ones that verify the launchers, so
# they must call the real thing; every other test must not.
_REAL_LAUNCH = app_index.launch
_REAL_LAUNCH_START_APP = app_index.launch_start_app
_REAL_TRY_DIRECT_LAUNCH = app_index.try_direct_launch


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

    _REAL_LAUNCH(Path("C:/x/notepad.lnk"))

    fake_startfile.assert_called_once_with("C:\\x\\notepad.lnk")


def test_try_direct_launch_returns_true_on_success(monkeypatch):
    fake_startfile = MagicMock()
    monkeypatch.setattr(app_index.os, "startfile", fake_startfile, raising=False)

    assert _REAL_TRY_DIRECT_LAUNCH("notepad") is True
    fake_startfile.assert_called_once_with("notepad")


def test_try_direct_launch_returns_false_when_windows_cant_resolve_it(monkeypatch):
    fake_startfile = MagicMock(side_effect=OSError("not found"))
    monkeypatch.setattr(app_index.os, "startfile", fake_startfile, raising=False)

    assert _REAL_TRY_DIRECT_LAUNCH("not-a-real-command-xyz") is False


def test_start_apps_parses_the_windows_app_list(monkeypatch):
    """Store/UWP apps have no .lnk anywhere, so the shortcut scan cannot see
    Calculator, Settings, Photos or the modern Notepad at all. Get-StartApps is
    Windows' own list and is the only source that covers them."""
    payload = ('[{"Name":"Calculator","AppID":"Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},'
               '{"Name":"Settings","AppID":"windows.immersivecontrolpanel_cw5n1h2txyewy!x"}]')
    monkeypatch.setattr(app_index, "_START_APPS_CACHE", None)
    monkeypatch.setattr(app_index.subprocess, "run",
                        lambda *a, **kw: MagicMock(stdout=payload))

    apps = app_index.start_apps(refresh=True)

    assert apps["calculator"].startswith("Microsoft.WindowsCalculator")
    assert "settings" in apps


def test_a_single_app_comes_back_unwrapped(monkeypatch):
    """ConvertTo-Json emits a bare object rather than a one-element array when
    only one app matches, which would otherwise iterate over dict keys."""
    monkeypatch.setattr(app_index, "_START_APPS_CACHE", None)
    monkeypatch.setattr(app_index.subprocess, "run",
                        lambda *a, **kw: MagicMock(stdout='{"Name":"Solo","AppID":"solo!App"}'))
    assert app_index.start_apps(refresh=True) == {"solo": "solo!App"}


def test_a_failed_app_list_does_not_break_the_shortcut_index(monkeypatch):
    def boom(*a, **kw):
        raise OSError("powershell missing")

    monkeypatch.setattr(app_index, "_START_APPS_CACHE", None)
    monkeypatch.setattr(app_index.subprocess, "run", boom)
    assert app_index.start_apps(refresh=True) == {}
    assert app_index.resolve_start_app("calculator", {}) is None


def test_exact_match_beats_a_plausible_fuzzy_one():
    """"calculator" must never be talked into being "Calendar"."""
    apps = {"calculator": "calc!App", "calendar": "cal!App"}
    assert app_index.resolve_start_app("calculator", apps) == "calc!App"


def test_prefix_match_handles_a_shortened_name():
    apps = {"calculator": "calc!App"}
    assert app_index.resolve_start_app("calc", apps) == "calc!App"


def test_substring_match_finds_a_qualified_name():
    """People say "store", Windows calls it "Microsoft Store"."""
    apps = {"microsoft store": "store!App", "microsoft edge": "edge!App"}
    assert app_index.resolve_start_app("store", apps) == "store!App"


def test_shortest_containing_name_wins():
    apps = {"code": "code!App", "visual studio code insiders build": "insiders!App"}
    assert app_index.resolve_start_app("code", apps) == "code!App"


def test_launch_start_app_uses_the_appsfolder_shell_path(monkeypatch):
    """explorer.exe is the only launcher that understands shell:AppsFolder, and
    it is the only way to start a UWP app by ID."""
    popen = MagicMock()
    monkeypatch.setattr(app_index.subprocess, "Popen", popen)

    _REAL_LAUNCH_START_APP("Some.App_abc!App")

    args = popen.call_args[0][0]
    assert args[0] == "explorer.exe"
    assert args[1] == r"shell:AppsFolder\Some.App_abc!App"
