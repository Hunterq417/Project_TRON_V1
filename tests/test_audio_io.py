# tests/test_audio_io.py
from unittest.mock import MagicMock

import numpy as np

import audio_io


def test_drain_mic_joins_queued_chunks():
    audio = audio_io.DuplexAudio()
    audio.mic_queue.put(b"abc")
    audio.mic_queue.put(b"def")

    assert audio.drain_mic() == b"abcdef"
    assert audio.drain_mic() == b""  # empty queue drains to empty bytes


def test_play_chunk_writes_int16_frames_to_out_stream():
    audio = audio_io.DuplexAudio()
    fake_out = MagicMock()
    audio._out_stream = fake_out

    pcm = np.array([1, 2, 3], dtype=np.int16).tobytes()
    audio.play_chunk(pcm)

    written = fake_out.write.call_args[0][0]
    assert written.shape == (3, 1)
    assert written.dtype == np.int16


def test_play_chunk_ignores_empty_bytes():
    audio = audio_io.DuplexAudio()
    fake_out = MagicMock()
    audio._out_stream = fake_out

    audio.play_chunk(b"")

    fake_out.write.assert_not_called()


def test_start_stop_lifecycle(monkeypatch):
    fake_in = MagicMock()
    fake_out = MagicMock()
    monkeypatch.setattr(audio_io.sd, "InputStream", MagicMock(return_value=fake_in))
    monkeypatch.setattr(audio_io.sd, "OutputStream", MagicMock(return_value=fake_out))

    audio = audio_io.DuplexAudio()
    audio.start()
    fake_in.start.assert_called_once()
    fake_out.start.assert_called_once()

    audio.stop()
    fake_in.stop.assert_called_once()
    fake_out.stop.assert_called_once()
