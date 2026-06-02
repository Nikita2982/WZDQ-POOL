from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import librosa
import numpy as np
from mutagen import File as MutagenFile

from analysis.camelot import musical_key_to_camelot

PITCH_CLASSES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR_TEMPLATE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_TEMPLATE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass(slots=True)
class AudioAnalysisResult:
    artist: str | None
    title: str
    duration_sec: int | None
    bpm: float | None
    musical_key: str | None
    camelot_key: str | None
    energy_level: float | None
    file_hash: str
    analyzed_at: datetime
    analysis_notes: str | None = None

    def to_payload(self) -> dict:
        return asdict(self)


class AudioAnalyzer:
    def analyze_file(self, file_path: str | Path) -> AudioAnalysisResult:
        path = Path(file_path)
        metadata = self._read_tags(path)
        duration = metadata["duration_sec"]
        title = metadata["title"] or path.stem

        y, sr = librosa.load(path.as_posix(), mono=True, duration=180)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = self._normalize_tempo(tempo)

        musical_key = self._estimate_key(y=y, sr=sr)
        camelot_key = musical_key_to_camelot(musical_key)
        energy_level = self._estimate_energy(y, sr)

        return AudioAnalysisResult(
            artist=metadata["artist"],
            title=title,
            duration_sec=duration,
            bpm=round(bpm, 2) if bpm else None,
            musical_key=musical_key,
            camelot_key=camelot_key,
            energy_level=round(energy_level, 3) if energy_level is not None else None,
            file_hash=self._hash_file(path),
            analyzed_at=datetime.now(timezone.utc),
            analysis_notes="Local MVP analysis via librosa",
        )

    def _read_tags(self, path: Path) -> dict:
        audio = MutagenFile(path.as_posix(), easy=True)
        if audio is None:
            return {"artist": None, "title": path.stem, "duration_sec": None}
        duration = int(getattr(audio.info, "length", 0)) or None
        artist = self._first(audio.get("artist"))
        title = self._first(audio.get("title")) or path.stem
        return {"artist": artist, "title": title, "duration_sec": duration}

    @staticmethod
    def _first(values: list[str] | None) -> str | None:
        return values[0] if values else None

    @staticmethod
    def _estimate_energy(y: np.ndarray, sr: int) -> float | None:
        if y.size == 0:
            return None
        rms = librosa.feature.rms(y=y)[0]
        spectral = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        rms_score = float(np.clip(np.mean(rms) * 10, 0, 1))
        spectral_score = float(np.clip(np.mean(spectral) / 5000, 0, 1))
        return float(np.clip((rms_score * 0.7) + (spectral_score * 0.3), 0, 1))

    @staticmethod
    def _normalize_tempo(tempo) -> float | None:
        if tempo is None:
            return None
        if isinstance(tempo, np.ndarray):
            if tempo.size == 0:
                return None
            return float(np.asarray(tempo).reshape(-1)[0])
        return float(tempo)

    def _estimate_key(self, y: np.ndarray, sr: int) -> str | None:
        if y.size == 0:
            return None
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        profile = np.mean(chroma, axis=1)

        best_score = float("-inf")
        best_key: str | None = None
        for idx, pitch in enumerate(PITCH_CLASSES):
            major_score = float(np.corrcoef(profile, np.roll(MAJOR_TEMPLATE, idx))[0, 1])
            minor_score = float(np.corrcoef(profile, np.roll(MINOR_TEMPLATE, idx))[0, 1])
            if major_score > best_score:
                best_score = major_score
                best_key = f"{pitch} Major"
            if minor_score > best_score:
                best_score = minor_score
                best_key = f"{pitch} Minor"
        return best_key

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
