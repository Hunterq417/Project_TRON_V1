# perception.py
import io

import cv2
from PIL import ImageGrab


def capture_screen_jpeg() -> bytes:
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def capture_camera_jpeg() -> bytes:
    cap = cv2.VideoCapture(0)
    try:
        if not cap.isOpened():
            raise RuntimeError("could not open the camera")
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("could not read a frame from the camera")
        success, buf = cv2.imencode(".jpg", frame)
        if not success:
            raise RuntimeError("could not encode the camera frame")
        return buf.tobytes()
    finally:
        cap.release()
