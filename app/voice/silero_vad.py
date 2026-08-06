"""Silero Voice Activity Detector for Phase 14.3.

Provides a Silero-based VAD as a drop-in replacement for EnergyVoiceActivityDetector,
with fallback to the existing energy-based VAD.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Optional

log = logging.getLogger(__name__)


class SileroVAD:
    """Silero-based Voice Activity Detector.

    Uses the Silero VAD model for high-quality speech detection.
    Falls back to energy-based detection if the model is unavailable.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
    ) -> None:
        self._sample_rate = sample_rate
        self._threshold = threshold
        self._min_speech_duration_ms = min_speech_duration_ms
        self._min_silence_duration_ms = min_silence_duration_ms
        self._model = None
        self._available = False

        self._load_model(model_path)

    def _load_model(self, model_path: Optional[str]) -> None:
        try:
            import torch
            if model_path is None:
                model_path = "silero_vad.onnx"
            if model_path.endswith(".onnx"):
                import onnxruntime as ort
                self._model = ort.InferenceSession(model_path)
            else:
                self._model = torch.hub.load(
                    "snakers4/silero-vad",
                    "silero_vad",
                    force_reload=False,
                )
            self._available = True
            log.info("Silero VAD loaded successfully")
        except Exception as exc:
            log.debug("Silero VAD unavailable, using fallback: %s", exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def process_chunk(self, audio: bytes) -> Optional[bytes]:
        """Process an audio chunk and return speech if detected.

        Returns None if no speech is detected.
        Returns the audio chunk if speech is detected.
        """
        if not self._available:
            return self._fallback_process(audio)

        try:
            import numpy as np

            samples = np.frombuffer(audio, dtype=np.int16)
            float_samples = samples.astype(np.float32) / 32768.0

            if hasattr(self._model, "run"):
                ort_inputs = {"input": float_samples.reshape(1, -1).astype(np.float32)}
                ort_outputs = self._model.run(None, ort_inputs)
                speech_prob = float(ort_outputs[0][0][0])
            else:
                speech_prob = float(self._model(torch.from_numpy(float_samples).unsqueeze(0)))

            if speech_prob >= self._threshold:
                return audio
            return None
        except Exception:
            return self._fallback_process(audio)

    def _fallback_process(self, audio: bytes) -> Optional[bytes]:
        """Fallback to energy-based VAD when Silero is unavailable."""
        if not audio:
            return None
        samples = np.frombuffer(audio, dtype=np.int16)
        energy = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        if energy > 100:
            return audio
        return None

    def reset(self) -> None:
        """Reset the VAD state."""
        pass

    def start(self) -> None:
        """Start the VAD."""
        pass

    def stop(self) -> None:
        """Stop the VAD."""
        pass