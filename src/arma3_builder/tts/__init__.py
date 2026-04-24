"""Optional text-to-speech synthesis for voice-over placeholders.

Two providers:

  * ``piper`` — local Piper binary via subprocess. Zero-cost, CPU-only.
  * ``stub``  — writes a one-byte placeholder OGG for every line (keeps
    the sentences.bikb schema honest without actual audio).

Pick via the ``ARMA3_TTS_PROVIDER`` env. Missions always run end-to-end
even when TTS is unavailable — `speech[]` just points at empty placeholders
the designer later replaces with real recordings.
"""
from .provider import (
    NullTTS,
    PiperTTS,
    TTSProvider,
    TTSResult,
    get_provider,
    synthesise_dialogue,
)

__all__ = [
    "NullTTS",
    "PiperTTS",
    "TTSProvider",
    "TTSResult",
    "get_provider",
    "synthesise_dialogue",
]
