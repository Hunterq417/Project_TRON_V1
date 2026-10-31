# security_scan.py
import subprocess
import threading
import time

import memory

_status_lock = threading.Lock()
_status = {"state": "never_run"}  # never_run | running | completed | failed

# Start-MpScan exiting cleanly only means the scan ran, not that it was clean.
# Ask Defender what it detected since the scan began; "UNKNOWN" when that query
# itself is refused, so TRON says it doesn't know rather than "all clear".
_SCAN_SCRIPT = (
    "$s = Get-Date; Start-MpScan -ScanType QuickScan -ErrorAction Stop; "
    "try { @(Get-MpThreatDetection -ErrorAction Stop | "
    "Where-Object { $_.InitialDetectionTime -ge $s }).Count } "
    "catch { 'UNKNOWN' }"
)


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
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _SCAN_SCRIPT],
            check=True, capture_output=True, text=True, timeout=1800,
            # No console: a scan runs for minutes, and without this it parks a
            # terminal window on screen for the whole of it.
            stdin=subprocess.DEVNULL, creationflags=0x08000000,
        ).stdout
        last = (out or "").strip().splitlines()[-1:] or [""]
        threats = int(last[0]) if last[0].strip().isdigit() else None
        with _status_lock:
            _status["state"] = "completed"
            _status["threats"] = threats
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
        threats = _status.get("threats")
    if state == "never_run":
        return "no scan has been run yet, sir"
    if state == "running":
        return "the scan is still running, sir"
    if state == "completed":
        if threats is None:
            return ("the last scan completed, sir, but I couldn't read what it "
                    "found — check Windows Security for details")
        if threats:
            return (f"the last scan completed and Defender detected {threats} "
                    "threat(s), sir — check Windows Security")
        return "the last scan completed with no threats detected, sir"
    return "the last scan failed to complete — check Windows Security for details, sir"
