# Upgrading from hotkey to the "hey tron" wake word

The code side of this is done: `wake_trigger.OpenWakeWordTrigger` runs its own
continuous mic stream, dispatches detections to their own thread (so a long
conversation never blocks the real-time audio callback), and is wired into
`main.py` whenever `config.json` sets `"wake_mode": "openwakeword"`. The only
thing missing is the trained model file itself — `models/tron.onnx` — since
training is a data/offline step, not application code, and needs resources
(PyTorch, several GB of datasets) this project doesn't otherwise depend on.

Until that file exists, `wake_mode` should stay `"hotkey"` — `OpenWakeWordTrigger`
raises a clear `FileNotFoundError` on startup if the model is missing, rather
than silently failing to listen.

## Generating a "hey tron" model with openWakeWord

openWakeWord supports fully synthetic training — it generates training audio
for your target phrase with a TTS voice generator plus room/noise
augmentation, so you don't have to record yourself saying "hey tron" dozens
of times.

1. Open a new Google Colab notebook and select a GPU runtime (Runtime →
   Change runtime type → T4 GPU). CPU training works but is slow enough to
   not be worth it for this step.
2. Follow openWakeWord's `notebooks/automatic_model_training.ipynb`
   (https://github.com/dscripka/openWakeWord), setting the target phrase to
   `"hey tron"`.
3. Download the resulting `.onnx` model from Colab and place it at
   `models/tron.onnx` in this project (the filename's stem — `tron` — is
   what `OpenWakeWordTrigger` uses to read the model's prediction score, so
   it must stay `tron.onnx` unless you also update `wakeword_model_path` in
   `config.json` to match a different name).
4. Set `"wake_mode": "openwakeword"` in `config.json`. Optionally tune the
   detection threshold — `OpenWakeWordTrigger`'s default is `0.5`; lower it
   if "hey tron" isn't triggering reliably, raise it if it's triggering on
   background noise or unrelated speech.
5. Run `python main.py` (or the built `.exe`) and say "hey tron" — the
   console/log prints `Say "hey tron" to talk` instead of the hotkey message
   when wake-word mode is active, confirming it picked up the new mode.

## Reverting to the hotkey

Set `"wake_mode": "hotkey"` back in `config.json` at any time — no need to
delete `models/tron.onnx`, it's simply unused while in hotkey mode.
