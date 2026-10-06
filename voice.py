"""Phase 3 — Jarvis's voice.

Local text-to-speech with Piper. Loads the voice once, synthesizes to raw
audio, and plays it through the default output device.
"""

import threading

import numpy as np
import sounddevice as sd
from piper import PiperVoice

import config


def _is_hindi(text: str) -> bool:
    """True if the text contains Devanagari (Hindi) characters."""
    return any("ऀ" <= c <= "ॿ" for c in text)


class Voice:
    def __init__(self) -> None:
        print(f"Loading TTS voice '{config.TTS_VOICE}'...")
        self.voice = PiperVoice.load(f"voices/{config.TTS_VOICE}.onnx")
        self._play_lock = threading.Lock()  # serialize playback across threads
        # optional Hindi voice, used automatically for Devanagari text
        self.hindi = None
        if config.TTS_VOICE_HINDI:
            try:
                self.hindi = PiperVoice.load(f"voices/{config.TTS_VOICE_HINDI}.onnx")
                print(f"Loaded Hindi TTS voice '{config.TTS_VOICE_HINDI}'.")
            except Exception as e:
                print(f"Hindi voice unavailable ({e}); English only.")

    def synth(self, text: str) -> tuple[np.ndarray, int] | None:
        """Synthesize text -> (audio, sample_rate), or None if empty.
        Picks the Hindi voice automatically when the text is Devanagari."""
        if not text.strip():
            return None
        voice = self.hindi if (self.hindi and _is_hindi(text)) else self.voice
        chunks = [
            np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
            for chunk in voice.synthesize(text)
        ]
        if not chunks:
            return None
        return np.concatenate(chunks), voice.config.sample_rate

    def say(self, text: str) -> None:
        result = self.synth(text)
        if result is None:
            return
        audio, sr = result
        with self._play_lock:
            sd.play(audio, samplerate=sr, blocking=True)
