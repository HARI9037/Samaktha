"""Provider-agnostic wake-word interfaces and openWakeWord adapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class WakeWordDetector(ABC):
    @abstractmethod
    def enable(self) -> None: ...
    @abstractmethod
    def disable(self) -> None: ...
    @abstractmethod
    def detect(self, audio: bytes) -> Optional[str]: ...
    @property
    @abstractmethod
    def is_enabled(self) -> bool: ...


class OpenWakeWordDetector(WakeWordDetector):
    """Local openWakeWord adapter.

    ``model_paths`` maps display phrases to local openWakeWord model files.
    Keeping paths configurable avoids coupling VoiceManager to a particular
    model distribution while still supporting both requested phrases.
    """

    def __init__(
        self,
        model_paths: Optional[dict[str, str]] = None,
        threshold: float = 0.5,
        phrases: Optional[list[str]] = None,
    ) -> None:
        self.model_paths = model_paths or {}
        self.threshold = threshold
        self.phrases = phrases or ["Samaktha", "Hey Samaktha"]
        self._model = None
        self._enabled = False
        self.last_confidence = 0.0

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError("Wake model missing: install openwakeword") from exc
        paths = [self.model_paths[p] for p in self.phrases if p in self.model_paths]
        if not paths:
            raise RuntimeError("Wake model missing")
        try:
            self._model = Model(wakeword_models=paths)
        except Exception as exc:
            raise RuntimeError("Wake model failed to load") from exc

    def enable(self) -> None:
        self._ensure_model()
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def detect(self, audio: bytes) -> Optional[str]:
        if not self._enabled:
            return None
        import numpy as np
        samples = np.frombuffer(audio, dtype=np.int16)
        scores = self._model.predict(samples)
        self.last_confidence = max((float(score) for score in scores.values()), default=0.0)
        for phrase in self.phrases:
            for name, score in scores.items():
                if phrase.lower().replace(" ", "_") in name.lower() and float(score) >= self.threshold:
                    return phrase
        return None

    @property
    def is_enabled(self) -> bool:
        return self._enabled


class NullWakeWordDetector(WakeWordDetector):
    def __init__(self) -> None:
        self._enabled = False
    def enable(self) -> None: self._enabled = True
    def disable(self) -> None: self._enabled = False
    def detect(self, audio: bytes) -> Optional[str]: return None
    @property
    def is_enabled(self) -> bool: return self._enabled
