# tests/test_system_status.py
from unittest.mock import MagicMock

import system_status


def _battery(monkeypatch, percent, plugged, secsleft):
    monkeypatch.setattr(system_status.psutil, "sensors_battery",
                        lambda: MagicMock(percent=percent, power_plugged=plugged,
                                          secsleft=secsleft))


def test_battery_on_mains_reports_charging(monkeypatch):
    _battery(monkeypatch, 62, True, 3600)
    assert system_status.battery_status() == "battery is at 62 percent and charging, sir"


def test_full_battery_is_not_described_as_charging(monkeypatch):
    _battery(monkeypatch, 100, True, 0)
    assert "fully charged" in system_status.battery_status()


def test_battery_reports_time_remaining_when_unplugged(monkeypatch):
    _battery(monkeypatch, 55, False, 5400)  # 90 minutes
    reply = system_status.battery_status()
    assert "1 hours 30 minutes" in reply


def test_unknown_time_remaining_is_omitted_rather_than_guessed(monkeypatch):
    """psutil reports a negative sentinel when Windows has not estimated a
    runtime yet; printing it as a duration would be an invented number."""
    _battery(monkeypatch, 80, False, -2)
    reply = system_status.battery_status()
    assert "80 percent" in reply and "-" not in reply.split("percent")[1]


def test_a_machine_without_a_battery_says_so(monkeypatch):
    monkeypatch.setattr(system_status.psutil, "sensors_battery", lambda: None)
    assert "no battery" in system_status.battery_status()


def test_hardware_status_includes_cpu_memory_and_gpu(monkeypatch):
    monkeypatch.setattr(system_status.psutil, "cpu_percent", lambda interval=None: 23.0)
    monkeypatch.setattr(system_status.psutil, "virtual_memory",
                        lambda: MagicMock(percent=50.0, total=16 * 1024**3,
                                          available=8 * 1024**3))
    monkeypatch.setattr(system_status, "_gpu_line", lambda: "GPU is at 10 percent")
    reply = system_status.hardware_status()
    assert "CPU is at 23 percent" in reply
    assert "memory 50 percent" in reply
    assert "GPU is at 10 percent" in reply


def test_hardware_status_works_without_a_gpu(monkeypatch):
    monkeypatch.setattr(system_status.psutil, "cpu_percent", lambda interval=None: 5.0)
    monkeypatch.setattr(system_status.psutil, "virtual_memory",
                        lambda: MagicMock(percent=40.0, total=8 * 1024**3,
                                          available=4 * 1024**3))
    monkeypatch.setattr(system_status, "_gpu_line", lambda: "")
    assert "GPU" not in system_status.hardware_status()


def test_high_memory_is_called_out(monkeypatch):
    monkeypatch.setattr(system_status.psutil, "cpu_percent", lambda interval=None: 10.0)
    monkeypatch.setattr(system_status.psutil, "virtual_memory",
                        lambda: MagicMock(percent=95.0, total=8 * 1024**3,
                                          available=int(0.4 * 1024**3)))
    monkeypatch.setattr(system_status, "_gpu_line", lambda: "")
    assert "Memory is very high" in system_status.hardware_status()


def test_gpu_line_is_empty_when_nvidia_smi_is_absent(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(system_status.subprocess, "run", boom)
    assert system_status._gpu_line() == ""


def test_gpu_line_parses_nvidia_smi_output(monkeypatch):
    monkeypatch.setattr(system_status.subprocess, "run",
                        lambda *a, **kw: MagicMock(stdout="29, 1638, 8188, 63\n"))
    line = system_status._gpu_line()
    assert "29 percent" in line and "63 degrees" in line


def test_malformed_gpu_output_is_ignored_rather_than_crashing(monkeypatch):
    monkeypatch.setattr(system_status.subprocess, "run",
                        lambda *a, **kw: MagicMock(stdout="not,really,numbers,here\n"))
    assert system_status._gpu_line() == ""
