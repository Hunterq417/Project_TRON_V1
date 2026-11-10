# Training a wake word ("hey friday")

TRON listens for three wake words:

| Say | Model | Starts as |
|---|---|---|
| "hey tron" | `models/tron.onnx` (included) | whoever is active |
| "hey jarvis" | ships with openWakeWord | JARVIS |
| "hey friday" | `models/hey_friday.onnx`, which **you train once** | FRIDAY |

Nobody publishes a "hey friday" model, so you have to make one. It's free and takes about an hour, almost all
of it unattended:

1. Open https://github.com/dscripka/openWakeWord, go to "Training New Models", and open the automatic
   training notebook it links in Google Colab.
2. Set `target_word` to `hey friday`. Leave the other settings as they are.
3. Choose Runtime > Run all. The notebook generates thousands of synthetic voices saying the phrase, then
   trains on them. Use a GPU runtime (Runtime > Change runtime type) to keep it under an hour.
4. Download the `.onnx` file it produces, rename it to `hey_friday.onnx`, and put it in TRON's `models`
   folder. That's the folder next to `TRON.exe`, or `models\` in the repository.
5. Restart TRON. "hey friday" now works and wakes TRON as FRIDAY.

If a wake word triggers too often or too rarely, retrain it with more steps, or say the phrase more clearly.
Until `hey_friday.onnx` exists, say "hey tron, switch to Friday" instead.
