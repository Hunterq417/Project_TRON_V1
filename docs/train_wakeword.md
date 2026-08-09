# Upgrading from hotkey to the "TRON" wake word

The MVP ships with a `Ctrl+Alt+T` hotkey trigger (`wake_trigger.HotkeyTrigger`)
instead of true always-listening wake-word detection, because training a
custom wake-word model is a data/offline step, not application code.

## Generating a "TRON" model with openWakeWord

openWakeWord supports fully synthetic training — it generates training audio
for your target phrase with a TTS voice generator plus room/noise
augmentation, so you don't have to record yourself saying "TRON" dozens of
times.

1. `pip install openwakeword` (adds `onnxruntime`)
2. Follow openWakeWord's `notebooks/automatic_model_training.ipynb`
   (https://github.com/dscripka/openWakeWord) with target phrase `"tron"`.
   CPU training works but is slow; a free Colab GPU runtime is much faster.
3. Export the trained model to `models/tron.onnx` in this project.
4. Set `"wake_mode": "openwakeword"` in `config.json`.
5. Add an `OpenWakeWordTrigger` to `wake_trigger.py` with the same shape as
   `HotkeyTrigger` — a constructor taking `on_trigger: Callable[[], None]`,
   plus a `feed(pcm_int16_chunk)` method called from the mic audio callback
   in `audio_io.py` that runs `openwakeword.Model.predict()` and calls
   `on_trigger()` past your chosen confidence threshold.
6. Wire it into `main.py`'s `if cfg.wake_mode != "hotkey"` branch.
