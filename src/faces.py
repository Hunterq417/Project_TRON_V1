# faces.py
"""Who's in front of the camera: face detection + recognition, entirely on this PC.

* Detector: SCRFD-10G (InsightFace's successor to RetinaFace) - boxes and 5 landmarks per face.
* Recognizer: ArcFace ResNet-50 (InsightFace w600k_r50) - a 512-number fingerprint of an aligned face.
* People: memory/faces.json keeps each enrolled person's fingerprints (a few per person, never photos).
  A face matches the person whose fingerprints it's most similar to, if the similarity clears MATCH.

Both models are InsightFace's pretrained buffalo_l pack (models/faces/), run with onnxruntime and OpenCV -
no TensorFlow/PyTorch. InsightFace licenses these models for non-commercial use.
Only people who agreed should be enrolled; TRON never sends a face anywhere.
"""
import json
import threading
import time

import cv2
import numpy as np

import config

MATCH = 0.40            # cosine similarity for "same person" (ArcFace r50: impostors sit around 0.0-0.25)
DET_SIZE = 640
DET_THRESHOLD = 0.5
SAMPLES = 5             # fingerprints kept per enrolment
_lock = threading.Lock()
_models = {}
# where ArcFace expects the eyes, nose and mouth corners in its 112x112 input
_ARCFACE_DST = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                         [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def _model_dir():
    return config.app_dir() / "models" / "faces"


def _session(name):
    import onnxruntime as ort
    with _lock:
        if name not in _models:
            path = _model_dir() / name
            if not path.exists():
                raise RuntimeError(f"the face model {name} isn't in {path.parent}")
            _models[name] = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _models[name]


# --------------------------------------------------------------------------- detection (SCRFD)
def detect(image: np.ndarray):
    """[(box x1,y1,x2,y2, score, landmarks 5x2)] for each face in a BGR image, biggest first."""
    session = _session("det_10g.onnx")
    h, w = image.shape[:2]
    scale = DET_SIZE / max(h, w)
    resized = cv2.resize(image, (int(w * scale), int(h * scale)))
    canvas = np.zeros((DET_SIZE, DET_SIZE, 3), np.uint8)
    canvas[:resized.shape[0], :resized.shape[1]] = resized
    blob = cv2.dnn.blobFromImage(canvas, 1 / 128, (DET_SIZE, DET_SIZE), (127.5, 127.5, 127.5), swapRB=True)
    outs = session.run(None, {session.get_inputs()[0].name: blob})
    faces = []
    for i, stride in enumerate((8, 16, 32)):
        scores, boxes, kps = outs[i].reshape(-1), outs[i + 3].reshape(-1, 4) * stride, outs[i + 6].reshape(-1, 10) * stride
        n = DET_SIZE // stride
        centers = np.stack(np.mgrid[:n, :n][::-1], axis=-1).reshape(-1, 2).astype(np.float32) * stride
        centers = np.repeat(centers, 2, axis=0)                 # two anchors per position
        keep = np.where(scores >= DET_THRESHOLD)[0]
        for k in keep:
            cx, cy = centers[k]
            box = np.array([cx - boxes[k, 0], cy - boxes[k, 1], cx + boxes[k, 2], cy + boxes[k, 3]]) / scale
            marks = (np.stack([cx + kps[k, 0::2], cy + kps[k, 1::2]], axis=-1)) / scale
            faces.append((box, float(scores[k]), marks))
    faces = _nms(faces)
    return sorted(faces, key=lambda f: -(f[0][2] - f[0][0]) * (f[0][3] - f[0][1]))


def _nms(faces, iou=0.4):
    faces = sorted(faces, key=lambda f: -f[1])
    kept = []
    for f in faces:
        x1, y1, x2, y2 = f[0]
        overlap = False
        for k in kept:
            a1, b1, a2, b2 = k[0]
            inter = max(0, min(x2, a2) - max(x1, a1)) * max(0, min(y2, b2) - max(y1, b1))
            union = (x2 - x1) * (y2 - y1) + (a2 - a1) * (b2 - b1) - inter
            if union > 0 and inter / union > iou:
                overlap = True
                break
        if not overlap:
            kept.append(f)
    return kept


# --------------------------------------------------------------------------- recognition (ArcFace)
def embed(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """The face's 512-number fingerprint, unit length."""
    matrix, _ = cv2.estimateAffinePartial2D(landmarks.astype(np.float32), _ARCFACE_DST, method=cv2.LMEDS)
    face = cv2.warpAffine(image, matrix, (112, 112), borderValue=0)
    session = _session("w600k_r50.onnx")
    blob = cv2.dnn.blobFromImage(face, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
    vector = session.run(None, {session.get_inputs()[0].name: blob})[0][0]
    return vector / (np.linalg.norm(vector) + 1e-9)


# --------------------------------------------------------------------------- people
def _gallery_path():
    return config.app_dir() / "memory" / "faces.json"


def gallery() -> dict:
    try:
        data = json.loads(_gallery_path().read_text(encoding="utf-8"))
        return {name: np.array(vectors, dtype=np.float32) for name, vectors in data.items()}
    except (OSError, ValueError):
        return {}


def _save(people: dict) -> None:
    path = _gallery_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({n: np.round(v, 5).tolist() for n, v in people.items()}), encoding="utf-8")


def identify(vector: np.ndarray, people: dict = None):
    """(name, similarity) of the closest enrolled person, or (None, best similarity)."""
    people = gallery() if people is None else people
    best, best_sim = None, 0.0
    for name, vectors in people.items():
        sim = float(np.max(vectors @ vector))
        if sim > best_sim:
            best, best_sim = name, sim
    return (best, best_sim) if best_sim >= MATCH else (None, best_sim)


def camera_frames(count: int = 1, gap: float = 0.25):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    try:
        if not cap.isOpened():
            raise RuntimeError("I couldn't open the camera")
        for _ in range(5):          # let exposure settle
            cap.read()
        frames = []
        for _ in range(count):
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
            time.sleep(gap)
        if not frames:
            raise RuntimeError("the camera gave no picture")
        return frames
    finally:
        cap.release()


def who(frame: np.ndarray, people: dict = None) -> list:
    """[(name or None, similarity, box)] for every face in the frame."""
    people = gallery() if people is None else people
    out = []
    for box, _score, marks in detect(frame):
        name, sim = identify(embed(frame, marks), people)
        out.append((name, round(sim, 2), box))
    return out


def annotate(frame: np.ndarray, found: list) -> np.ndarray:
    """The frame with a labelled box on each face: green for someone known, amber for a stranger."""
    image = frame.copy()
    for name, sim, box in found:
        x1, y1, x2, y2 = (int(v) for v in box)
        colour = (80, 220, 120) if name else (60, 180, 245)
        cv2.rectangle(image, (x1, y1), (x2, y2), colour, 2)
        label = f"{name} {sim:.2f}" if name else "unknown"
        cv2.putText(image, label, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
    return image


def look(cfg=None):
    """(annotated BGR frame, [(name, similarity, box)]) from one camera picture - for the control panel."""
    if not _camera_allowed(cfg):
        raise RuntimeError("the camera is switched off in Settings")
    frame = camera_frames(1)[0]
    found = who(frame)
    return annotate(frame, found), found


# --------------------------------------------------------------------------- tools
def _camera_allowed(cfg) -> bool:
    return bool(getattr(cfg, "camera_enabled", False)) if cfg is not None else True


def enroll_face(args, cfg=None) -> str:
    """Tool: learn the face in front of the camera under a name (the person must be the only face)."""
    name = str((args or {}).get("name", "")).strip()
    if not name:
        return "whose face is this, sir? Tell me their name."
    if not _camera_allowed(cfg):
        return "the camera is switched off in Settings, sir"
    try:
        frames = camera_frames(SAMPLES * 2, gap=0.2)
    except RuntimeError as exc:
        return f"{exc}, sir"
    vectors = []
    for frame in frames:
        found = detect(frame)
        if len(found) == 1:
            vectors.append(embed(frame, found[0][2]))
        elif len(found) > 1:
            return "I can see more than one face, sir. Only the person to enrol should be in view."
    if len(vectors) < 3:
        return "I couldn't see a face clearly, sir. Face the camera in good light and try again."
    people = gallery()
    for other, vecs in people.items():   # don't file one person under two names
        if other.lower() != name.lower() and float(np.max(vecs @ vectors[0])) >= MATCH + 0.1:
            return f"that face already belongs to {other}, sir. Forget {other} first if that's wrong."
    current = [v for v in people.get(name, np.zeros((0, 512), np.float32))]
    people[name] = np.array((current + vectors)[-SAMPLES * 2:], dtype=np.float32)
    _save(people)
    return f"I'll recognise {name} from now on, sir ({len(vectors)} looks saved)."


def who_is_here(args=None, cfg=None) -> str:
    """Tool: who TRON can see through the camera right now."""
    if not _camera_allowed(cfg):
        return "the camera is switched off in Settings, sir"
    try:
        frame = camera_frames(1)[0]
    except RuntimeError as exc:
        return f"{exc}, sir"
    found = who(frame)
    if not found:
        return "I can't see anyone in front of the camera, sir"
    names = [n for n, _s, _b in found if n]
    strangers = sum(1 for n, _s, _b in found if not n)
    parts = names + ([f"{strangers} person{'s' if strangers > 1 else ''} I don't know"] if strangers else [])
    return "I can see " + ", ".join(parts) + ", sir"


def forget_face(args, cfg=None) -> str:
    name = str((args or {}).get("name", "")).strip()
    people = gallery()
    match = next((n for n in people if n.lower() == name.lower()), None)
    if not match:
        return f"I don't know a face called {name}, sir"
    del people[match]
    _save(people)
    return f"forgot {match}'s face, sir"


def known_faces(args=None, cfg=None) -> str:
    people = gallery()
    return ("I know the faces of " + ", ".join(people) + ", sir") if people else "I don't know anyone's face yet, sir"


# --------------------------------------------------------------------------- for the brain's context
_seen = {"name": None, "at": 0.0}


def refresh(cfg=None) -> None:
    """Look who's at the PC, on a background thread (a camera frame + two models take ~1-2 s, which must never
    delay an answer). Only when the camera is allowed and someone is enrolled. Never raises."""
    if cfg is None or not _camera_allowed(cfg) or not _gallery_path().exists():
        return

    def look():
        try:
            people = gallery()
            found = who(camera_frames(1)[0], people) if people else []
            _seen["name"] = next((n for n, _s, _b in found if n), None)
        except Exception:
            _seen["name"] = None
        _seen["at"] = time.time()
    threading.Thread(target=look, daemon=True).start()


def context(max_age: float = 300.0) -> str:
    """A line for the system prompt when TRON recently recognised who's at the PC, else ""."""
    if _seen["name"] and time.time() - _seen["at"] < max_age:
        return (f"The person at the PC right now is {_seen['name']} (recognised by face through the camera). "
                "Address them by name and use what you know about them.")
    return ""
