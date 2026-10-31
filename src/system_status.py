# system_status.py
"""Read-only telemetry: battery, CPU, memory, GPU.

Everything here is a question TRON gets asked out loud ("how's my battery",
"is anything pegging the CPU"), so each function returns a spoken sentence
rather than a dict. Nothing here changes machine state.

CPU temperature is deliberately absent. Windows exposes it through
MSAcpi_ThermalZoneTemperature, which on this machine (and most laptops without
a vendor driver) refuses to answer without administrator rights — and TRON
does not run elevated on purpose. GPU temperature comes from nvidia-smi, which
does work unelevated, so thermals are reported where they can actually be read
instead of guessed.
"""
import subprocess

import psutil

_NVIDIA_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu"


def battery_status(args=None, cfg=None) -> str:
    battery = psutil.sensors_battery()
    if battery is None:
        return "this machine has no battery, sir — it's running on mains"
    percent = round(battery.percent)
    if battery.power_plugged:
        state = "charging" if percent < 100 else "fully charged"
        return f"battery is at {percent} percent and {state}, sir"
    secs = battery.secsleft
    if secs is None or secs < 0:
        return f"battery is at {percent} percent, sir, running on battery"
    hours, minutes = divmod(int(secs) // 60, 60)
    remaining = f"{hours} hours {minutes} minutes" if hours else f"{minutes} minutes"
    return f"battery is at {percent} percent, sir — about {remaining} left"


def _gpu_line() -> str:
    """GPU load, memory and temperature, or "" when there is no NVIDIA GPU."""
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_NVIDIA_QUERY}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
            # No console: without this every reading flashes a terminal window
            # over whatever the user is doing.
            stdin=subprocess.DEVNULL, creationflags=0x08000000,
        ).stdout.strip().splitlines()
    except Exception:
        return ""
    if not out:
        return ""
    parts = [p.strip() for p in out[0].split(",")]
    if len(parts) < 4:
        return ""
    load, used, total, temp = parts[:4]
    try:
        used_gb = int(used) / 1024
        total_gb = int(total) / 1024
    except ValueError:
        return ""
    return (f"GPU is at {load} percent, using {used_gb:.1f} of {total_gb:.1f} "
            f"gigabytes, {temp} degrees")


def hardware_status(args=None, cfg=None) -> str:
    """CPU, memory and GPU in one spoken line."""
    # A blocking sample: cpu_percent() without an interval returns the average
    # since the last call, which is meaningless on the first one.
    cpu = psutil.cpu_percent(interval=0.4)
    memory = psutil.virtual_memory()
    used_gb = (memory.total - memory.available) / 1024 ** 3
    total_gb = memory.total / 1024 ** 3

    parts = [
        f"CPU is at {cpu:.0f} percent",
        f"memory {memory.percent:.0f} percent, {used_gb:.1f} of {total_gb:.1f} gigabytes",
    ]
    gpu = _gpu_line()
    if gpu:
        parts.append(gpu)

    line = ", ".join(parts) + ", sir"
    if memory.percent >= 90:
        line += ". Memory is very high — worth closing something"
    elif cpu >= 90:
        line += ". The CPU is pinned — something is working hard"
    return line
