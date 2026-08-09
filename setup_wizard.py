# setup_wizard.py
import json
import tkinter as tk
from tkinter import messagebox, ttk

import autostart
import config


def build_config_dict(form_values: dict) -> dict:
    """Turns raw wizard form values into the config.json dict shape. Pure — no I/O."""
    return {
        "gemini_api_key": form_values["gemini_api_key"].strip(),
        "wake_mode": "hotkey",
        "hotkey": form_values.get("hotkey", "").strip() or "ctrl+alt+t",
        "wakeword_model_path": "models/tron.onnx",
        "persona_path": "persona.txt",
        "silence_timeout_s": 45.0,
        "voice_name": "Orus",
        "model_name": "gemini-3.1-flash-live-preview",
        "smtp_host": form_values.get("smtp_host", "").strip(),
        "smtp_port": int(form_values.get("smtp_port") or 465),
        "smtp_user": form_values.get("smtp_user", "").strip(),
        "smtp_app_password": form_values.get("smtp_app_password", "").strip(),
        "camera_enabled": bool(form_values.get("camera_enabled", False)),
        "screen_enabled": bool(form_values.get("screen_enabled", False)),
    }


def write_config_file(path, config_dict: dict) -> None:
    path.write_text(json.dumps(config_dict, indent=2), encoding="utf-8")


def run_first_time_setup() -> None:
    """Blocks on a tkinter window until the user submits, then writes config.json
    (and enables autostart if requested)."""
    root = tk.Tk()
    root.title("TRON — first-time setup")

    fields = {}

    def add_field(key, label_text, row, default="", show=None):
        ttk.Label(root, text=label_text).grid(row=row, column=0, sticky="w", padx=8, pady=4)
        var = tk.StringVar(value=default)
        ttk.Entry(root, textvariable=var, width=40, show=show or "").grid(
            row=row, column=1, padx=8, pady=4
        )
        fields[key] = var

    add_field("gemini_api_key", "Gemini API key", 0, show="*")
    add_field("hotkey", "Hotkey", 1, default="ctrl+alt+t")
    add_field("smtp_host", "SMTP host (optional)", 2)
    add_field("smtp_port", "SMTP port (optional)", 3, default="465")
    add_field("smtp_user", "SMTP user (optional)", 4)
    add_field("smtp_app_password", "SMTP app password (optional)", 5, show="*")

    autostart_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        root, text="Start TRON automatically when I log in", variable=autostart_var
    ).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=4)

    camera_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(root, text="Enable camera access", variable=camera_var).grid(
        row=7, column=0, columnspan=2, sticky="w", padx=8, pady=4
    )

    screen_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(root, text="Enable screen reading", variable=screen_var).grid(
        row=8, column=0, columnspan=2, sticky="w", padx=8, pady=4
    )

    def on_save():
        if not fields["gemini_api_key"].get().strip():
            messagebox.showerror("TRON setup", "A Gemini API key is required.")
            return
        form_values = {key: var.get() for key, var in fields.items()}
        form_values["camera_enabled"] = camera_var.get()
        form_values["screen_enabled"] = screen_var.get()
        config_dict = build_config_dict(form_values)
        write_config_file(config.CONFIG_PATH, config_dict)
        if autostart_var.get():
            try:
                autostart.enable()
            except Exception as exc:
                messagebox.showwarning(
                    "TRON setup",
                    f"Couldn't enable autostart: {exc}\nYou can still run TRON manually.",
                )
        root.destroy()

    ttk.Button(root, text="Save & Start", command=on_save).grid(
        row=9, column=0, columnspan=2, pady=10
    )

    root.mainloop()
