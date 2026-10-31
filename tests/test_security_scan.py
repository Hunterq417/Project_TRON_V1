# tests/test_security_scan.py
from unittest.mock import MagicMock

import pytest

import security_scan


@pytest.fixture(autouse=True)
def reset_status():
    with security_scan._status_lock:
        security_scan._status["state"] = "never_run"
    yield
    with security_scan._status_lock:
        security_scan._status["state"] = "never_run"


def test_check_scan_status_never_run():
    assert "no scan has been run" in security_scan.check_scan_status({}, None)


def test_scan_for_malware_starts_background_thread(monkeypatch):
    monkeypatch.setattr(security_scan.subprocess, "run", MagicMock())
    monkeypatch.setattr(
        security_scan.threading, "Thread",
        lambda target, daemon: MagicMock(start=target),
    )

    result = security_scan.scan_for_malware({}, None)

    assert "scan started" in result.lower()


def test_scan_for_malware_refuses_concurrent_scans():
    with security_scan._status_lock:
        security_scan._status["state"] = "running"

    result = security_scan.scan_for_malware({}, None)

    assert "already running" in result.lower()


def test_run_scan_marks_completed_on_success(monkeypatch):
    monkeypatch.setattr(security_scan.subprocess, "run", MagicMock(return_value=MagicMock(stdout="0\n")))
    logged = []
    monkeypatch.setattr(security_scan.memory, "log_activity", lambda entry: logged.append(entry))

    security_scan._run_scan()

    assert security_scan._status["state"] == "completed"
    assert logged[0]["tool"] == "scan_for_malware"


def test_run_scan_marks_failed_on_error(monkeypatch):
    monkeypatch.setattr(
        security_scan.subprocess, "run", MagicMock(side_effect=OSError("powershell not found"))
    )
    logged = []
    monkeypatch.setattr(security_scan.memory, "log_activity", lambda entry: logged.append(entry))

    security_scan._run_scan()

    assert security_scan._status["state"] == "failed"
    assert "failed" in logged[0]["result"].lower()


def test_check_scan_status_running():
    with security_scan._status_lock:
        security_scan._status["state"] = "running"
    assert "still running" in security_scan.check_scan_status({}, None)


def test_check_scan_status_completed():
    with security_scan._status_lock:
        security_scan._status["state"] = "completed"
    assert "completed" in security_scan.check_scan_status({}, None)


def test_check_scan_status_failed():
    with security_scan._status_lock:
        security_scan._status["state"] = "failed"
    assert "failed" in security_scan.check_scan_status({}, None)


def test_completed_scan_reports_detections_not_blanket_all_clear(monkeypatch):
    """A clean exit from Start-MpScan is not a clean machine."""
    logged = []
    monkeypatch.setattr(security_scan.memory, "log_activity", logged.append)
    for stdout, expected in (("2\n", "detected 2"), ("0\n", "no threats"),
                             ("UNKNOWN\n", "couldn't read")):
        monkeypatch.setattr(security_scan.subprocess, "run",
                            MagicMock(return_value=MagicMock(stdout=stdout)))
        security_scan._run_scan()
        assert expected in security_scan.check_scan_status({}, None)
