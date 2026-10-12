"""Tests for AudioAdapter conversions and resampling."""

import struct
import numpy as np
from app.utils.audio import AudioAdapter


def test_audio_adapter_resampling():
    adapter = AudioAdapter(
        telecmi_sample_rate=8000,
        gemini_input_sample_rate=16000,
        gemini_output_sample_rate=24000
    )

    # Generate 100ms of 8000Hz 16-bit mono PCM (800 samples = 1600 bytes)
    sample_count = 800
    samples = [int(1000 * np.sin(2 * np.pi * 440 * t / 8000)) for t in range(sample_count)]
    pcm_8k = struct.pack(f"<{sample_count}h", *samples)

    # Convert 8kHz to 16kHz for Gemini input
    pcm_16k = adapter.telecmi_to_gemini(pcm_8k)
    assert len(pcm_16k) == 1600 * 2  # Doubled sample count

    # Convert 24kHz Gemini output to 8kHz TeleCMI format
    samples_24k = [int(1000 * np.sin(2 * np.pi * 440 * t / 24000)) for t in range(2400)]
    pcm_24k = struct.pack(f"<2400h", *samples_24k)
    pcm_out_8k = adapter.gemini_to_telecmi(pcm_24k)
    assert len(pcm_out_8k) == 800 * 2  # 1/3 sample count


def test_mulaw_conversions():
    # Test PCM to mu-law and back
    samples = [0, 500, -500, 1000, -1000, 10000, -10000]
    pcm_in = struct.pack(f"<{len(samples)}h", *samples)

    mulaw = AudioAdapter.pcm16_to_mulaw(pcm_in)
    assert len(mulaw) == len(samples)

    pcm_restored = AudioAdapter.mulaw_to_pcm16(mulaw)
    assert len(pcm_restored) == len(pcm_in)


def test_empty_audio_handling():
    adapter = AudioAdapter()
    assert adapter.telecmi_to_gemini(b"") == b""
    assert adapter.gemini_to_telecmi(b"") == b""


def test_remove_dc_offset():
    samples = np.array([100, 105, 95, 100], dtype=np.int16)
    cleaned = AudioAdapter.remove_dc_offset(samples)
    assert abs(int(np.mean(cleaned))) <= 1


def test_voice_clarity_and_speech_detection():
    adapter = AudioAdapter()

    # 1. Soft voice (amplitude 400, 500Hz) -> boosted cleanly and speech detected
    t = np.arange(320)
    speech = (400 * np.sin(2 * np.pi * 500 * t / 16000)).astype(np.int16).tobytes()
    boosted_speech, is_speech = adapter.process_incoming_pcm(speech, is_ai_speaking=False)
    out_samples = np.frombuffer(boosted_speech, dtype=np.int16)
    assert np.max(np.abs(out_samples)) > 400  # Boosted for clarity
    assert is_speech is True


def test_ai_speaking_barge_in_guard():
    adapter = AudioAdapter()
    t = np.arange(320)

    # Moderate background chatter (amplitude 200) while AI is speaking -> no barge-in
    bg_sound = (200 * np.sin(2 * np.pi * 400 * t / 16000)).astype(np.int16).tobytes()
    _, is_speech = adapter.process_incoming_pcm(bg_sound, is_ai_speaking=True)
    assert is_speech is False

    # Loud decisive customer speech (amplitude 2500) while AI is speaking -> triggers barge-in
    loud_speech = (2500 * np.sin(2 * np.pi * 400 * t / 16000)).astype(np.int16).tobytes()
    # Need 2 consecutive frames for barge-in
    adapter.process_incoming_pcm(loud_speech, is_ai_speaking=True)
    _, is_speech = adapter.process_incoming_pcm(loud_speech, is_ai_speaking=True)
    assert is_speech is True
