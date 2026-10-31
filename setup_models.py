"""Downloads the offline models TRON needs into models/ (run once after cloning; safe to run again).

    .venv\\Scripts\\python setup_models.py           everything
    .venv\\Scripts\\python setup_models.py --skip faces voices

What it fetches (about 1.3 GB in total):
    speech     NVIDIA Parakeet TDT 0.6B v2, int8 ONNX       hearing in Local/offline mode and dictation
    voice      Kokoro-82M ONNX + voices                     the Kokoro voices (Windows voices need nothing)
    faces      InsightFace buffalo_l: SCRFD + ArcFace       face recognition (non-commercial licence)
    voices     3D-Speaker CAM++                             voice recognition
    wakeword   openWakeWord's shared front-end models       "hey tron" (TRON's own models/tron.onnx is in git)

The local brain is not here: install Ollama (https://ollama.com/download) and run `ollama pull qwen3.5:4b`.
"""
import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.relative_to(ROOT)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {dest.name} ...", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def speech():
    from huggingface_hub import snapshot_download
    snapshot_download("istupakov/parakeet-tdt-0.6b-v2-onnx", local_dir=MODELS / "parakeet-tdt-0.6b-v2",
                      allow_patterns=["*int8.onnx", "config.json", "vocab.txt"])


def voice():
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
    fetch(base + "kokoro-v1.0.onnx", MODELS / "kokoro" / "kokoro-v1.0.onnx")
    fetch(base + "voices-v1.0.bin", MODELS / "kokoro" / "voices-v1.0.bin")


def faces():
    wanted = {"det_10g.onnx", "w600k_r50.onnx"}
    folder = MODELS / "faces"
    if all((folder / n).exists() for n in wanted):
        print("  have models/faces")
        return
    print("  downloading InsightFace buffalo_l (~280 MB) ...", flush=True)
    data = urllib.request.urlopen("https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip").read()
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.split("/")[-1] in wanted:
                (folder / name.split("/")[-1]).write_bytes(z.read(name))


def voices():
    fetch("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
          "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx", MODELS / "voices" / "campplus.onnx")


def wakeword():
    import openwakeword.utils
    openwakeword.utils.download_models()
    print("  openWakeWord front-end ready")


STEPS = {"speech": speech, "voice": voice, "faces": faces, "voices": voices, "wakeword": wakeword}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip", nargs="*", default=[], choices=list(STEPS))
    args = parser.parse_args()
    failed = []
    for name, step in STEPS.items():
        if name in args.skip:
            continue
        print(f"[{name}]")
        try:
            step()
        except Exception as exc:
            failed.append(name)
            print(f"  FAILED: {exc}")
    print("\nDone." if not failed else f"\nSome downloads failed ({', '.join(failed)}); run this again to retry.")
    print("Local brain: install Ollama, then run:  ollama pull qwen3.5:4b")
    sys.exit(1 if failed else 0)
