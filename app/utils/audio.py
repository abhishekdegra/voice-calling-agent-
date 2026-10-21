"""Audio format adapters and converters for TeleCMI <-> Gemini Live session."""

import struct
from typing import Optional
import numpy as np


class AudioAdapter:
    """
    Handles bidirectional audio conversion between TeleCMI telephony streams and Gemini Live API.
    
    Standard specs:
    - Gemini Input: PCM 16-bit signed, Little-Endian, Mono, 16000 Hz (or 24000 Hz)
    - Gemini Output: PCM 16-bit signed, Little-Endian, Mono, 24000 Hz
    - TeleCMI / PIOPIY Input/Output: PCM 16-bit linear or G.711 Mu-law at 8000 Hz or 16000 Hz
    """

    def __init__(
        self,
        telecmi_sample_rate: int = 16000,
        gemini_input_sample_rate: int = 16000,
        gemini_output_sample_rate: int = 24000
    ):
        self.telecmi_sample_rate = telecmi_sample_rate
        self.gemini_input_sample_rate = gemini_input_sample_rate
        self.gemini_output_sample_rate = gemini_output_sample_rate
        self._hangover_frames: int = 0
        self._consecutive_speech_frames: int = 0

    @staticmethod
    def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
        """Convert G.711 mu-law bytes to 16-bit signed linear PCM bytes."""
        lut = AudioAdapter._get_mulaw_expansion_table()
        pcm_samples = [lut[b] for b in mulaw_bytes]
        return struct.pack(f"<{len(pcm_samples)}h", *pcm_samples)

    @staticmethod
    def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
        """Convert 16-bit signed linear PCM bytes to G.711 mu-law bytes."""
        num_samples = len(pcm_bytes) // 2
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes)
        lut = AudioAdapter._get_pcm_to_mulaw_table()
        out = bytearray(len(samples))
        for i, s in enumerate(samples):
            clamped = max(-32768, min(32767, s))
            out[i] = lut[(clamped + 32768) >> 2]
        return bytes(out)

    @staticmethod
    def resample_pcm16(pcm_bytes: bytes, in_rate: int, out_rate: int) -> bytes:
        """Resample 16-bit mono PCM bytes from in_rate to out_rate using linear interpolation."""
        if in_rate == out_rate or not pcm_bytes:
            return pcm_bytes

        num_samples = len(pcm_bytes) // 2
        if num_samples == 0:
            return b""

        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        
        duration = len(samples) / in_rate
        target_len = int(round(duration * out_rate))
        if target_len == 0:
            return b""

        old_indices = np.linspace(0, len(samples) - 1, num=len(samples))
        new_indices = np.linspace(0, len(samples) - 1, num=target_len)
        resampled = np.interp(new_indices, old_indices, samples).astype(np.int16)
        return resampled.tobytes()

    def telecmi_to_gemini(self, audio_chunk: bytes, is_mulaw: bool = False) -> bytes:
        """
        Converts customer audio from TeleCMI format to Gemini Live PCM 16-bit input format.
        """
        if not audio_chunk:
            return b""

        if is_mulaw:
            pcm16 = self.mulaw_to_pcm16(audio_chunk)
        else:
            pcm16 = audio_chunk

        if self.telecmi_sample_rate != self.gemini_input_sample_rate:
            pcm16 = self.resample_pcm16(
                pcm16, 
                self.telecmi_sample_rate, 
                self.gemini_input_sample_rate
            )

        return pcm16

    @staticmethod
    def remove_dc_offset(samples: np.ndarray) -> np.ndarray:
        """Removes DC bias/offset without attenuating voice frequencies."""
        if len(samples) < 2:
            return samples
        mean_val = int(np.mean(samples))
        return np.clip(samples.astype(np.int32) - mean_val, -32768, 32767).astype(np.int16)

    @staticmethod
    def calculate_energy(samples: np.ndarray) -> tuple[float, int]:
        """Returns (rms_energy, peak_amplitude) of 16-bit PCM samples."""
        if len(samples) == 0:
            return 0.0, 0
        float_s = samples.astype(np.float32)
        rms = float(np.sqrt(np.mean(float_s ** 2)))
        peak = int(np.max(np.abs(samples)))
        return rms, peak

    @staticmethod
    def is_ringback_tone(samples: np.ndarray, sample_rate: int = 16000) -> bool:
        """
        Detects Indian & global telecom ringback tones (typically 400Hz - 450Hz sinusoidal dual-tones).
        Ringback tones exhibit low zero-crossing variance and narrow-band harmonic concentration,
        distinguishable from broadband human speech.
        """
        if len(samples) < 320:
            return False
        
        # Calculate zero crossing rate
        zero_crossings = np.sum(np.diff(samples > 0) != 0)
        zcr = (zero_crossings * sample_rate) / (2.0 * len(samples))
        
        # Telecom ringback tones (380Hz to 480Hz) have ZCR tightly bounded around 380 - 480 Hz
        if 360 <= zcr <= 500:
            float_s = samples.astype(np.float32)
            rms = float(np.sqrt(np.mean(float_s ** 2)))
            # If amplitude is consistent with dial tone (> 150 RMS)
            if rms >= 100.0:
                return True
        return False

    def process_incoming_pcm(
        self,
        pcm16: bytes,
        is_ai_speaking: bool = False,
        recent_ai_peak: int = 0,
        is_call_answered: bool = False
    ) -> tuple[bytes, bool, float, int]:
        """
        Acoustic Echo Cancellation (AEC) & Voice Clarity Processing:
        - Filters out telephone ringback / dial tones before pickup so bot doesn't speak during ringing.
        - Suppresses speakerphone acoustic echo during AI speech via adaptive thresholding.
        - Preserves soft human affirmations ('haan', 'ji', 'theek hai') with telephony AGC.
        - Returns (clean_pcm16_bytes, is_speech, rms, peak).
        """
        if not pcm16:
            return b"", False, 0.0, 0

        num_samples = len(pcm16) // 2
        if num_samples == 0:
            return b"", False, 0.0, 0

        raw_samples = np.frombuffer(pcm16, dtype=np.int16)
        cleaned_samples = self.remove_dc_offset(raw_samples)
        float_s = cleaned_samples.astype(np.float32)
        rms, peak = self.calculate_energy(cleaned_samples)

        # 1. Ringback tone guard: Ringing audio should NEVER be treated as customer voice (only before pickup)
        if not is_call_answered and self.is_ringback_tone(cleaned_samples, self.gemini_input_sample_rate):
            self._consecutive_speech_frames = 0
            return b"", False, rms, peak

        # 2. Telephony Voice AGC (Automatic Gain Control):
        # Dynamically scales cellular phone speech up to clear telephony levels
        if peak >= 140 and rms >= 24.0:
            target_gain = min(4.5, max(1.2, 18000.0 / max(peak, 1600)))
            boosted_samples = np.clip(float_s * target_gain, -32768, 32767).astype(np.int16)
        else:
            boosted_samples = cleaned_samples

        # 3. Acoustic Echo Cancellation & Adaptive Barge-In Threshold:
        # When AI is actively speaking, speakerphone acoustics bleed AI voice back into phone mic.
        # We raise threshold adaptively relative to AI volume and require multi-frame vocal persistence.
        if is_ai_speaking:
            # Dynamic AEC floor: scales with AI output amplitude
            dynamic_peak_threshold = max(420, min(1500, int(recent_ai_peak * 0.38)))
            dynamic_rms_threshold = max(140.0, min(450.0, dynamic_peak_threshold * 0.32))
            is_active = (peak >= dynamic_peak_threshold and rms >= dynamic_rms_threshold)
            required_frames = 3  # ~60-90ms vocal persistence to filter speaker reflection
        else:
            is_active = (peak >= 200 and rms >= 32.0)
            required_frames = 1

        if is_active:
            self._consecutive_speech_frames += 1
            is_speech = self._consecutive_speech_frames >= required_frames
        else:
            self._consecutive_speech_frames = 0
            is_speech = False

        return boosted_samples.tobytes(), is_speech, rms, peak

    def gemini_to_telecmi(self, audio_chunk: bytes, to_mulaw: bool = False) -> bytes:
        """
        Converts Gemini Live output audio (24000 Hz PCM16) to TeleCMI format.
        """
        if not audio_chunk:
            return b""

        if self.gemini_output_sample_rate != self.telecmi_sample_rate:
            pcm_out = self.resample_pcm16(
                audio_chunk, 
                self.gemini_output_sample_rate, 
                self.telecmi_sample_rate
            )
        else:
            pcm_out = audio_chunk

        if to_mulaw:
            return self.pcm16_to_mulaw(pcm_out)

        return pcm_out

    @staticmethod
    def _get_mulaw_expansion_table():
        if not hasattr(AudioAdapter, "_mulaw_exp_table"):
            table = []
            for i in range(256):
                mu = ~i & 0xFF
                sign = -1 if (mu & 0x80) else 1
                exponent = (mu >> 4) & 0x07
                mantissa = mu & 0x0F
                sample = ((mantissa << 3) + 132) << exponent
                sample = (sample - 132) * sign
                table.append(sample)
            AudioAdapter._mulaw_exp_table = table
        return AudioAdapter._mulaw_exp_table

    @staticmethod
    def _get_pcm_to_mulaw_table():
        if not hasattr(AudioAdapter, "_pcm_to_mulaw_table"):
            table = bytearray(16384)
            for i in range(16384):
                pcm = (i << 2) - 32768
                table[i] = AudioAdapter._linear_to_mulaw_sample(pcm)
            AudioAdapter._pcm_to_mulaw_table = table
        return AudioAdapter._pcm_to_mulaw_table

    @staticmethod
    def _linear_to_mulaw_sample(sample: int) -> int:
        BIAS = 0x84
        CLIP = 32635
        sign = 0x80 if sample < 0 else 0x00
        if sample < 0:
            sample = -sample
        if sample > CLIP:
            sample = CLIP
        sample += BIAS
        exponent = 7
        for exp in range(7, -1, -1):
            if sample & (1 << (exp + 7)):
                exponent = exp
                break
        mantissa = (sample >> (exponent + 3)) & 0x0F
        byte_val = ~(sign | (exponent << 4) | mantissa) & 0xFF
        return byte_val
