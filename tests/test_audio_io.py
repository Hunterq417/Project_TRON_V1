# tests/test_audio_io.py
from unittest.mock import MagicMock

import numpy as np
import pytest

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


def test_rms_level_silence_is_zero():
    silence = np.zeros(100, dtype=np.int16).tobytes()
    assert audio_io.rms_level(silence) == 0.0


def test_rms_level_empty_bytes_is_zero():
    assert audio_io.rms_level(b"") == 0.0


def test_rms_level_louder_audio_scores_higher():
    quiet = (np.ones(100, dtype=np.int16) * 500).tobytes()
    loud = (np.ones(100, dtype=np.int16) * 5000).tobytes()

    assert audio_io.rms_level(loud) > audio_io.rms_level(quiet)


def test_rms_level_is_clamped_to_one():
    full_scale = np.full(100, 32767, dtype=np.int16).tobytes()
    assert audio_io.rms_level(full_scale) == 1.0


def test_input_stream_uses_the_configured_device(monkeypatch):
    """The whole point of mic_device: a machine with 20 input endpoints can have
    a dead one as the Windows default, and silently listening to it looks
    identical to a broken app."""
    fake_sd = MagicMock()
    monkeypatch.setattr(audio_io, "sd", fake_sd)
    monkeypatch.setattr(audio_io, "input_devices", lambda: [(9, "HyperX Cloud II", 1)])

    audio_io.DuplexAudio(device="HyperX").start()

    # Resolved to an index on the way through: sounddevice cannot open an
    # ambiguous name itself, so resolve_input does it first.
    assert fake_sd.InputStream.call_args.kwargs["device"] == 9


def test_input_stream_defaults_to_the_system_device(monkeypatch):
    fake_sd = MagicMock()
    monkeypatch.setattr(audio_io, "sd", fake_sd)

    audio_io.DuplexAudio().start()

    assert fake_sd.InputStream.call_args.kwargs["device"] is None


def test_input_devices_skips_output_only_devices(monkeypatch):
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = [
        {"name": "A Mic", "max_input_channels": 1},
        {"name": "Speakers", "max_input_channels": 0},
    ]
    monkeypatch.setattr(audio_io, "sd", fake_sd)

    assert audio_io.input_devices() == [(0, "A Mic", 1)]


def test_microphone_name_resolves_the_configured_device(monkeypatch):
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = {"name": "Some Mic"}
    monkeypatch.setattr(audio_io, "sd", fake_sd)

    assert audio_io.microphone_name(device=3) == "Some Mic"
    fake_sd.query_devices.assert_called_once_with(3)


def test_microphone_name_falls_back_to_the_system_default(monkeypatch):
    fake_sd = MagicMock()
    fake_sd.default.device = [7, 4]
    fake_sd.query_devices.return_value = {"name": "Default Mic"}
    monkeypatch.setattr(audio_io, "sd", fake_sd)

    assert audio_io.microphone_name() == "Default Mic"
    fake_sd.query_devices.assert_called_once_with(7)


def test_rms_level_tolerates_an_odd_byte_count():
    """PCM16 samples are two bytes, so an odd-length buffer is malformed — but
    this runs on audio arriving from the network and gates the conversation's
    silence timeout, so it must not raise. One bad packet used to be enough to
    end a conversation."""
    assert audio_io.rms_level(b"\x00\x10\x00\x10\x7f") > 0.0
    assert audio_io.rms_level(b"\x7f") == 0.0


def test_record_alongside_captures_the_audio_the_model_scored(tmp_path):
    """Recorded via the trigger's own callback, not a second stream: comparing
    two wake-word models on a recording is only valid if it is the same audio
    the live model heard."""
    class FakeTrigger:
        def __init__(self):
            self.blocks = []
            self._on_score = None

        def _on_block(self, indata, frames, time_info, status):
            self.blocks.append(bytes(indata))

    trigger = FakeTrigger()
    recording = audio_io.record_alongside(trigger)

    pcm = np.full(160, 1234, dtype=np.int16).tobytes()
    trigger._on_block(pcm, 160, None, None)
    trigger._on_block(pcm, 160, None, None)

    assert trigger.blocks == [pcm, pcm], "the trigger must still see every block"

    out = recording.save(tmp_path / "heard.wav")
    assert out is not None
    import wave as _wave
    with _wave.open(out) as f:
        assert f.getframerate() == audio_io.SAMPLE_RATE_IN
        assert f.getnchannels() == 1
        assert f.readframes(f.getnframes()) == pcm + pcm


def test_record_alongside_saves_nothing_when_no_audio_arrived(tmp_path):
    class FakeTrigger:
        _on_score = None

        def _on_block(self, *a):
            pass

    recording = audio_io.record_alongside(FakeTrigger())
    assert recording.save(tmp_path / "empty.wav") is None


def test_resolve_input_picks_the_first_match_for_an_ambiguous_name(monkeypatch):
    """Windows lists the same physical mic once per audio API, so any name worth
    typing matches several devices. sounddevice raises on that; resolving it
    ourselves is what makes names usable at all."""
    monkeypatch.setattr(audio_io, "input_devices", lambda: [
        (2, "Microphone Array (Intel Smart ", 4),
        (10, "Microphone Array (Intel Smart Sound Technology)", 4),
    ])
    assert audio_io.resolve_input("Intel") == 2


def test_resolve_input_is_case_insensitive_and_passes_through(monkeypatch):
    monkeypatch.setattr(audio_io, "input_devices", lambda: [(7, "HyperX Cloud II", 1)])
    assert audio_io.resolve_input("hyperx") == 7
    assert audio_io.resolve_input(3) == 3
    assert audio_io.resolve_input(None) is None


def test_resolve_input_rejects_a_name_that_matches_nothing(monkeypatch):
    monkeypatch.setattr(audio_io, "input_devices", lambda: [(1, "Some Mic", 1)])
    with pytest.raises(ValueError, match="list-mics"):
        audio_io.resolve_input("not-a-real-device")


def test_resolve_output_matches_by_name(monkeypatch):
    """Outputs need name resolution as much as inputs: "Realtek" matches several
    endpoints (one per audio API) and sounddevice refuses an ambiguous name, so
    without this speaker_device could only be a number — and numbers shift when
    a headset is plugged in."""
    monkeypatch.setattr(audio_io, "output_devices", lambda: [
        (5, "Speaker (Realtek(R) Audio)", 2),
        (11, "Speaker (Realtek(R) Audio)", 2),
    ])
    assert audio_io.resolve_output("Realtek") == 5
    assert audio_io.resolve_output(3) == 3
    monkeypatch.setattr(audio_io, "windows_default_output", lambda: None)
    assert audio_io.resolve_output(None) is None   # unset follows Windows; None when it can't tell


def test_output_stream_uses_the_resolved_device(monkeypatch):
    fake_sd = MagicMock()
    monkeypatch.setattr(audio_io, "sd", fake_sd)
    monkeypatch.setattr(audio_io, "output_devices", lambda: [(5, "Speaker (Realtek)", 2)])
    monkeypatch.setattr(audio_io, "input_devices", lambda: [(2, "Mic Array", 1)])

    audio_io.DuplexAudio(device="Mic", output_device="Realtek").start()

    assert fake_sd.OutputStream.call_args.kwargs["device"] == 5
