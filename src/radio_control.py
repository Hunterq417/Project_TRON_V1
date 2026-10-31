# radio_control.py
"""Turning Bluetooth and Wi-Fi on and off.

Goes through the WinRT Radios API rather than `netsh interface set` or
`Disable-NetAdapter`, because those need administrator rights and this app
deliberately does not run elevated. RequestAccessAsync returned "Allowed" for a
normal user on this machine, so the radios can be driven without it.

Driven from PowerShell because reaching WinRT from Python would mean adding a
`winrt` dependency, and that is a large addition to a frozen build for two
calls. The awkward `Await` helper exists because PowerShell cannot await a
WinRT IAsyncOperation on its own.
"""
import subprocess

_KINDS = {"bluetooth": "Bluetooth", "wifi": "WiFi"}

_PREAMBLE = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
$access = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
if ($access -ne 'Allowed') { Write-Output "DENIED:$access"; exit 1 }
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) `
    ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
"""

# Only this fragment is formatted, never the preamble: the preamble is full of
# PowerShell braces that str.format would try to read as fields.
_SET_BODY = """
$target = $radios | Where-Object {{ $_.Kind -eq '{kind}' }} | Select-Object -First 1
if (-not $target) {{ Write-Output "MISSING"; exit 1 }}
$result = Await ($target.SetStateAsync('{state}')) ([Windows.Devices.Radios.RadioAccessStatus])
Write-Output "RESULT:$result"
"""

_STATUS = _PREAMBLE + """
foreach ($r in $radios) { Write-Output ("STATE:{0}={1}" -f $r.Kind, $r.State) }
"""


# The packaged app is windowed, so it has no console and no valid standard
# handles to hand a child process. PowerShell inherits those broken handles and
# can fail outright — radio_status worked from source and failed only in the
# frozen build until stdin was given somewhere real and the child was told not
# to try to allocate a console of its own.
_CREATE_NO_WINDOW = 0x08000000


def _run(script: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=45,
        stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW,
    )
    out = completed.stdout.strip()
    if not out and completed.stderr.strip():
        # Surfaced rather than swallowed: a silent failure here reads as "the
        # radio is broken" when the real problem is how the child was started.
        return "ERR:" + completed.stderr.strip().splitlines()[0][:160]
    return out


def set_radio(kind: str, enabled: bool) -> str:
    """Switch a radio on or off. Returns a line for TRON to say back."""
    key = str(kind).strip().lower().replace("-", "").replace(" ", "")
    if key not in _KINDS:
        return f"I can switch bluetooth or wifi, sir, not {kind}"
    label = "Bluetooth" if key == "bluetooth" else "Wi-Fi"
    try:
        out = _run(_PREAMBLE + _SET_BODY.format(
            kind=_KINDS[key], state="On" if enabled else "Off"))
    except Exception as exc:
        return f"I couldn't reach the {label} radio, sir ({exc})"

    if "MISSING" in out:
        return f"this machine has no {label} radio, sir"
    if "DENIED" in out:
        return (f"Windows refused access to the {label} radio, sir — it may be "
                "blocked in Settings, or by airplane mode")
    if "RESULT:Allowed" in out:
        verb = "on" if enabled else "off"
        # Worth saying out loud: switching Wi-Fi off cuts the connection this
        # very conversation is running over, so TRON goes quiet immediately
        # after and cannot be spoken to again until it is back on.
        if key == "wifi" and not enabled:
            return ("Wi-Fi is off, sir. I'll lose my connection now and won't hear "
                    "you until it's back on")
        return f"{label} is {verb}, sir"
    return f"I couldn't change the {label} radio, sir ({out or 'no response'})"


def radio_status() -> str:
    """What the radios are currently doing."""
    try:
        out = _run(_STATUS)
    except Exception as exc:
        return f"I couldn't read the radios, sir ({exc})"
    states = []
    for line in out.splitlines():
        if line.startswith("STATE:"):
            kind, _, state = line[len("STATE:"):].partition("=")
            label = "Bluetooth" if kind == "Bluetooth" else "Wi-Fi" if kind == "WiFi" else kind
            states.append(f"{label} is {state.lower()}")
    if not states:
        return "I couldn't read the radios, sir"
    return ", ".join(states) + ", sir"
