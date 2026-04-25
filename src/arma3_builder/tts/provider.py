"""TTS provider abstraction.

The real provider shells out to ``piper`` when it's on PATH; otherwise we
fall back to a null provider that writes tiny placeholder OGG files so
the generator's output is always complete (just silent).

Designers pick a real voice later by replacing the placeholder OGGs under
``missions/<mid>/sound/*.ogg``.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class TTSResult:
    ok: bool
    path: Path
    bytes_written: int = 0
    provider: str = ""


class TTSProvider(Protocol):
    name: str
    def synthesise(self, text: str, *, out_path: Path, voice: str = "") -> TTSResult: ...


# --------------------------------------------------------------------------- #
# Null provider — emits an empty placeholder. Used when Piper is missing
# or explicitly disabled, so the pipeline never fails on TTS.
# --------------------------------------------------------------------------- #


class NullTTS:
    name = "null"

    def synthesise(self, text: str, *, out_path: Path, voice: str = "") -> TTSResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")       # 0-byte OGG placeholder
        return TTSResult(ok=True, path=out_path, bytes_written=0, provider=self.name)


# --------------------------------------------------------------------------- #
# Piper provider (optional — only if the binary is on PATH).
# --------------------------------------------------------------------------- #


class PiperTTS:
    """Minimal Piper CLI wrapper.

    Expected invocation: `piper --model <voice.onnx> --output_file <out.wav>`
    then we pipe text via stdin. We convert WAV → OGG via ffmpeg if
    available; otherwise we keep the WAV (still valid in CfgSounds).
    """
    name = "piper"

    def __init__(self, *, voice_model: str | None = None) -> None:
        self.binary = shutil.which("piper")
        self.ffmpeg = shutil.which("ffmpeg")
        self.voice_model = voice_model or os.environ.get(
            "ARMA3_TTS_PIPER_MODEL", ""
        )

    @property
    def available(self) -> bool:
        return bool(self.binary and self.voice_model)

    def synthesise(self, text: str, *, out_path: Path, voice: str = "") -> TTSResult:
        if not self.available:
            return NullTTS().synthesise(text, out_path=out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wav = out_path.with_suffix(".wav")
        try:
            subprocess.run(
                [self.binary, "--model", self.voice_model,
                 "--output_file", str(wav)],
                input=text, text=True, timeout=30, check=True,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return NullTTS().synthesise(text, out_path=out_path)

        final = wav
        if self.ffmpeg and out_path.suffix.lower() == ".ogg":
            try:
                subprocess.run(
                    [self.ffmpeg, "-y", "-i", str(wav), str(out_path)],
                    check=True, capture_output=True, timeout=20,
                )
                wav.unlink(missing_ok=True)
                final = out_path
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                final = wav
        try:
            size = final.stat().st_size
        except OSError:
            size = 0
        return TTSResult(ok=True, path=final, bytes_written=size, provider=self.name)


# --------------------------------------------------------------------------- #
# Factory + high-level dialogue helper
# --------------------------------------------------------------------------- #


def get_provider() -> TTSProvider:
    prov = os.environ.get("ARMA3_TTS_PROVIDER", "null").lower()
    if prov == "piper":
        p = PiperTTS()
        return p if p.available else NullTTS()
    return NullTTS()


def _safe_filename(line_id: str, text: str) -> str:
    """Stable OGG filename that doesn't collide across dialog lines."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{line_id}_{digest}.ogg"


@dataclass
class DialogueLineAudio:
    line_id: str
    sound_path: str          # relative path inside the mission
    duration_seconds: float = 2.5


def synthesise_dialogue(
    lines: list[tuple[str, str]],           # [(line_id, text), ...]
    *,
    mission_dir: Path,
    provider: TTSProvider | None = None,
) -> list[DialogueLineAudio]:
    """Render each (line_id, text) pair into ``<mission>/sound/<file>.ogg``.

    Returns per-line descriptors that ``dialog.py`` pulls into the
    ``sentences.bikb`` ``speech[]`` array.
    """
    prov = provider or get_provider()
    out: list[DialogueLineAudio] = []
    for line_id, text in lines:
        fname = _safe_filename(line_id, text)
        sound_rel = f"sound/{fname}"
        target = mission_dir / sound_rel
        prov.synthesise(text, out_path=target)
        # Rough duration estimate: ~14 chars/sec English speech.
        duration = max(0.5, len(text) / 14.0)
        out.append(DialogueLineAudio(
            line_id=line_id, sound_path=sound_rel, duration_seconds=duration,
        ))
    return out
