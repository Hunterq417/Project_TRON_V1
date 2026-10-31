# tests/test_radio_control.py
from unittest.mock import MagicMock

import radio_control


def _fake_run(monkeypatch, stdout):
    monkeypatch.setattr(radio_control, "_run", MagicMock(return_value=stdout))


def test_turning_a_radio_on_reports_success(monkeypatch):
    _fake_run(monkeypatch, "RESULT:Allowed")
    assert radio_control.set_radio("bluetooth", True) == "Bluetooth is on, sir"


def test_turning_wifi_off_warns_that_the_connection_goes_with_it(monkeypatch):
    """Switching Wi-Fi off kills the network this very conversation runs over,
    so TRON goes silent straight after. Saying so first is the difference
    between a deliberate act and TRON appearing to crash."""
    _fake_run(monkeypatch, "RESULT:Allowed")
    reply = radio_control.set_radio("wifi", False)
    assert "lose my connection" in reply


def test_a_missing_radio_is_reported_plainly(monkeypatch):
    _fake_run(monkeypatch, "MISSING")
    assert "no Bluetooth radio" in radio_control.set_radio("bluetooth", True)


def test_denied_access_explains_itself(monkeypatch):
    _fake_run(monkeypatch, "DENIED:DeniedByUser")
    reply = radio_control.set_radio("wifi", True)
    assert "refused access" in reply and "airplane mode" in reply


def test_unknown_radio_kind_is_rejected_without_running_powershell(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(radio_control, "_run", run)
    assert "bluetooth or wifi" in radio_control.set_radio("nfc", True)
    run.assert_not_called()


def test_kind_is_forgiving_about_spelling(monkeypatch):
    """Spoken commands arrive transcribed, so "wi-fi" and "Wi Fi" both turn up."""
    _fake_run(monkeypatch, "RESULT:Allowed")
    for spelling in ("wifi", "Wi-Fi", "WI FI", " wifi "):
        assert radio_control.set_radio(spelling, True) == "Wi-Fi is on, sir"


def test_status_lists_both_radios(monkeypatch):
    _fake_run(monkeypatch, "STATE:WiFi=On\nSTATE:Bluetooth=Off")
    assert radio_control.radio_status() == "Wi-Fi is on, Bluetooth is off, sir"


def test_a_powershell_failure_does_not_raise(monkeypatch):
    def boom(script):
        raise OSError("powershell missing")

    monkeypatch.setattr(radio_control, "_run", boom)
    assert "couldn't reach" in radio_control.set_radio("bluetooth", True)
    assert "couldn't read" in radio_control.radio_status()
