# security_scan.py
import subprocess
import threading
import time

import memory

_status_lock = threading.Lock()
_status = {"state": "never_run"}  # never_run | running | completed | failed


def scan_for_malware(args, cfg) -> str:
    """Kicks off a Windows Defender quick scan in the background and returns immediately."""
    with _status_lock:
        if _status["state"] == "running":
            return "a scan is already running, sir"
        _status["state"] = "running"

    thread = threading.Thread(target=_run_scan, daemon=True)
    thread.start()
    return "scan started, sir — I'll let you know when it's finished"


def _run_scan() -> None:
    started_at = time.time()
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Start-MpScan -ScanType QuickScan"],
            check=True, capture_output=True, text=True, timeout=1800,
        )
        with _status_lock:
            _status["state"] = "completed"
        memory.log_activity({
            "tool": "scan_for_malware", "args": {},
            "result": f"quick scan completed in {int(time.time() - started_at)}s",
        })
    except Exception as exc:
        with _status_lock:
            _status["state"] = "failed"
        memory.log_activity({
            "tool": "scan_for_malware", "args": {}, "result": f"scan failed: {exc}",
        })


def check_scan_status(args, cfg) -> str:
    with _status_lock:
        state = _status["state"]
    if state == "never_run":
        return "no scan has been run yet, sir"
    if state == "running":
        return "the scan is still running, sir"
    if state == "completed":
        return "the last scan completed with no issues reported, sir"
    return "the last scan failed to complete — check Windows Security for details, sir"
