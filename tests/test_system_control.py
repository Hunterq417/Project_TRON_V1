# tests/test_system_control.py
from unittest.mock import MagicMock

import pytest

import system_control


def test_shutdown_pc_calls_shutdown_with_delay_and_comment(monkeypatch):
    fake_run = MagicMock()
    monkeypatch.setattr(system_control.subprocess, "run", fake_run)

    result = system_control.shutdown_pc({}, None)

    args, kwargs = fake_run.call_args
    cmd = args[0]
    assert cmd[0] == "shutdown"
    assert "/s" in cmd
    assert "/t" in cmd
    assert "30" in cmd
    assert "cancel shutdown" in result.lower()


def test_restart_pc_calls_shutdown_with_r_flag(monkeypatch):
    fake_run = MagicMock()
    monkeypatch.setattr(system_control.subprocess, "run", fake_run)

    result = system_control.restart_pc({}, None)

    args, kwargs = fake_run.call_args
    cmd = args[0]
    assert "/r" in cmd
    assert "restarting" in result.lower()


def test_shutdown_pc_failure_returns_message_instead_of_raising(monkeypatch):
    fake_run = MagicMock(side_effect=OSError("shutdown.exe not found"))
    monkeypatch.setattr(system_control.subprocess, "run", fake_run)

    result = system_control.shutdown_pc({}, None)

    assert "couldn't start" in result.lower()


def test_cancel_shutdown_success(monkeypatch):
    fake_run = MagicMock()
    monkeypatch.setattr(system_control.subprocess, "run", fake_run)

    result = system_control.cancel_shutdown({}, None)

    fake_run.assert_called_once_with(["shutdown", "/a"], check=True, capture_output=True, text=True,
        stdin=system_control.subprocess.DEVNULL,
        creationflags=system_control._CREATE_NO_WINDOW)
    assert "cancelled" in result.lower()


def test_cancel_shutdown_when_nothing_pending(monkeypatch):
    fake_run = MagicMock(
        side_effect=system_control.subprocess.CalledProcessError(1116, ["shutdown", "/a"])
    )
    monkeypatch.setattr(system_control.subprocess, "run", fake_run)

    result = system_control.cancel_shutdown({}, None)

    assert "no pending shutdown" in result.lower()
