"""Phase 2 — Jarvis's understanding.

Wraps faster-whisper: takes the recorded command audio (int16 numpy array
at 16 kHz) and returns the transcribed text. Model loads once and is reused.

Runs on the GPU (CUDA) when available for the bigger 'medium' multilingual
model; falls back to a fast CPU model if CUDA isn't usable.
"""

import os

import numpy as np

import config


def _register_cuda_dlls() -> None:
    """Add the pip-installed CUDA DLL folders to the search path (Windows)."""
    if os.name != "nt":
        return
    import sysconfig
    base = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
    for sub in ("cublas", "cudnn", "cuda_nvrtc"):
        d = os.path.join(base, sub, "bin")
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            except Exception:
                pass


class Transcriber:
    def __init__(self) -> None:
        from faster_whisper import WhisperModel
        _register_cuda_dlls()

        # try GPU first (fast + accurate medium), fall back to CPU
        try:
            print(f"Loading Whisper '{config.WHISPER_MODEL}' on GPU...")
            self.model = WhisperModel(
                config.WHISPER_MODEL, device="cuda", compute_type="float16",
            )
            # force a tiny inference to confirm CUDA actually works
            self.model.transcribe(np.zeros(16000, dtype=np.float32))
            self.device = "cuda"
            print("Whisper running on GPU.")
        except Exception as e:
            print(f"GPU unavailable ({e}); falling back to CPU model "
                  f"'{config.WHISPER_CPU_FALLBACK}'.")
            self.model = WhisperModel(
                config.WHISPER_CPU_FALLBACK, device="cpu", compute_type="int8",
            )
            self.device = "cpu"

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: int16 mono at 16 kHz -> recognized text."""
        samples = audio.astype(np.float32) / 32768.0
        segments, _info = self.model.transcribe(
            samples,
            language=config.WHISPER_LANGUAGE,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
