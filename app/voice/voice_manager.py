"""Voice frontend coordinator.

VoiceManager only translates audio into text, forwards text to
``AgentRuntime.handle_message`` and sends streamed response chunks to TTS.
It contains no planning, policy, provider, memory, or tool logic.
"""

from __future__ import annotations

import inspect
import logging
import asyncio
import time
import math
import struct
from dataclasses import dataclass
from typing import Any, Callable, Optional, AsyncIterator

from app.voice.config import VoiceConfig
from app.voice.events import VoiceEvent
from app.voice.metrics import VoiceMetricsCollector
from app.voice.microphone import MicrophoneInterface, NullMicrophone, SoundDeviceMicrophone
from app.voice.speaker import SpeakerInterface, NullSpeaker, SoundDeviceSpeaker
from app.voice.stt import SpeechToText, NullSpeechToText, FasterWhisperSTT
from app.voice.tts import TextToSpeech, NullTextToSpeech, PiperTTS
from app.voice.vad import VoiceActivityDetector, EnergyVoiceActivityDetector
from app.voice.wakeword import WakeWordDetector, NullWakeWordDetector, OpenWakeWordDetector
from app.voice.streaming_queue import SpeechChunkBuilder, SpeechChunkQueue
from app.voice.performance import VoicePerformanceReport
from app.voice.speech_formatter import SpeechFormatter, SpeechEmotion
from app.voice.personality import PersonalityEngine
from app.personality.intent_engine import IntentEngine

log = logging.getLogger(__name__)


@dataclass
class WakeDiagnostics:
    attempts: int = 0
    successful_detections: int = 0
    false_detections: int = 0
    confidence_sum: float = 0.0
    latency_sum: float = 0.0

    @property
    def average_confidence(self) -> float:
        return self.confidence_sum / self.successful_detections if self.successful_detections else 0.0

    @property
    def average_latency(self) -> float:
        return self.latency_sum / self.successful_detections if self.successful_detections else 0.0


class VoiceManager:
    """The only coordinator for the local voice frontend."""

    def __init__(
        self,
        config: VoiceConfig,
        runtime: Any,
        session_id: str = "default",
        microphone: Optional[MicrophoneInterface] = None,
        speaker: Optional[SpeakerInterface] = None,
        stt: Optional[SpeechToText] = None,
        tts: Optional[TextToSpeech] = None,
        vad: Optional[VoiceActivityDetector] = None,
        wakeword: Optional[WakeWordDetector] = None,
        on_event: Optional[Callable[[VoiceEvent, dict], None]] = None,
        metrics: Optional[VoiceMetricsCollector] = None,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._session_id = session_id
        local = config.enable_local_voice
        self._mic = microphone or (SoundDeviceMicrophone(config.channels) if local and config.microphone_enabled else NullMicrophone())
        self._speaker = speaker or (SoundDeviceSpeaker(config.channels) if local and config.speaker_enabled else NullSpeaker())
        self._stt = stt or (FasterWhisperSTT(config.whisper_model, config.language) if local and config.microphone_enabled else NullSpeechToText())
        self._tts = tts or (PiperTTS(config.voice_name, config.sample_rate) if local and config.speaker_enabled else NullTextToSpeech())
        self._vad = vad or EnergyVoiceActivityDetector(sample_rate=config.sample_rate)
        self._wakeword = wakeword or (
            OpenWakeWordDetector(threshold=config.wake_threshold, phrases=[config.wake_word_phrase, "Hey Samaktha"])
            if local and config.wake_active else NullWakeWordDetector()
        )
        self._on_event = on_event
        self._metrics = metrics
        self._running = False
        self._ptt_task: asyncio.Task | None = None
        self._wake_diagnostics = WakeDiagnostics()
        self._last_wake_at = 0.0
        self._active_utterance = False
        self._performance = VoicePerformanceReport()
        self._personality = PersonalityEngine(config.personality_profile)
        self._intent_engine = IntentEngine()
        self._formatter = SpeechFormatter(
            profile=self._personality,
            expand_numbers=config.expand_numbers,
            expand_abbreviations=config.expand_abbreviations,
            read_code=config.read_code,
            read_urls=config.read_urls,
            read_tables=config.read_tables,
            read_lists=config.read_lists,
        )
        self._speech_queue: SpeechChunkQueue | None = None
        self._speech_consumer: asyncio.Task | None = None
        self._barge_event = asyncio.Event()
        self._barge_seed: bytes | None = None
        self._last_barge_at = 0.0

    async def start(self) -> None:
        try:
            await self._stt.initialize()
            await self._tts.initialize()
            if self._config.microphone_enabled:
                await self._mic.open(self._config.sample_rate, self._config.input_device)
                self._vad.start()
            if self._config.speaker_enabled:
                await self._speaker.open(self._config.sample_rate, self._config.output_device)
            if self._config.wake_active:
                self._wakeword.enable()
            self._running = True
            if self._config.enable_push_to_talk and self._config.microphone_enabled:
                self._ptt_task = asyncio.create_task(self._poll_push_to_talk())
            if self._metrics:
                self._metrics.record_session_started()
            self._emit(VoiceEvent.VOICE_STARTED, {})
        except Exception as exc:
            await self._safe_shutdown()
            self._emit(VoiceEvent.VOICE_ERROR, {"stage": "startup", "error": self._friendly_error(exc)})
            raise RuntimeError(self._friendly_error(exc)) from exc

    async def stop(self) -> None:
        self._running = False
        if self._ptt_task:
            self._ptt_task.cancel()
            self._ptt_task = None
        self._vad.stop()
        self._wakeword.disable()
        await self._safe_shutdown()
        if self._metrics:
            self._metrics.record_session_stopped()
        self._emit(VoiceEvent.VOICE_STOPPED, {})

    async def _safe_shutdown(self) -> None:
        for operation in (
            self._mic.close,
            self._speaker.stop,
            self._speaker.close,
            self._stt.shutdown,
            self._tts.shutdown,
        ):
            try:
                await operation()
            except Exception:
                log.debug("voice shutdown operation failed", exc_info=True)

    async def process_voice(self) -> None:
        if not self._config.microphone_enabled:
            return
        if self._config.wake_active or self._config.always_listen:
            self._emit(VoiceEvent.VOICE_SLEEPING, {})
        else:
            self._emit(VoiceEvent.VOICE_LISTENING, {})
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._mic.read_chunk(), self._config.microphone_timeout)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                self._emit(VoiceEvent.VOICE_ERROR, {"stage": "microphone", "error": "Microphone unavailable"})
                await asyncio.sleep(0.5)
                continue

            if self._config.wake_active and not self._active_utterance:
                self._wake_diagnostics.attempts += 1
                started = time.monotonic()
                phrase = self._wakeword.detect(chunk) if self._wakeword.is_enabled else None
                if phrase is None or time.monotonic() - self._last_wake_at < self._config.cooldown_seconds:
                    continue
                confidence = float(getattr(self._wakeword, "last_confidence", self._config.wake_threshold))
                self._wake_diagnostics.successful_detections += 1
                self._wake_diagnostics.confidence_sum += confidence
                self._wake_diagnostics.latency_sum += time.monotonic() - started
                self._last_wake_at = time.monotonic()
                self._active_utterance = True
                self._emit(VoiceEvent.VOICE_WAKE_DETECTED, {"phrase": phrase, "confidence": confidence})
                self._emit(VoiceEvent.VOICE_LISTENING, {"phrase": phrase})
                self._emit(VoiceEvent.VOICE_RECORDING, {"phrase": phrase})
                self._vad.start()
                continue

            if self._config.wake_active and not self._active_utterance:
                continue
            audio = self._vad.process_chunk(chunk)
            if audio is not None:
                interrupted_audio = await self._handle_utterance(audio)
                self._active_utterance = False
                self._vad.on_ready()
                if interrupted_audio:
                    self._active_utterance = True
                    self._emit(VoiceEvent.LISTENING_AGAIN, {})
                    self._vad.process_chunk(interrupted_audio)
                else:
                    self._emit(VoiceEvent.VOICE_SLEEPING if self._config.wake_active else VoiceEvent.VOICE_READY, {})

    async def _runtime_stream(self, text: str) -> AsyncIterator[str]:
        result = self._runtime.handle_message(self._session_id, text)
        if inspect.isawaitable(result):
            result = await result
        if hasattr(result, "__aiter__"):
            async for chunk in result:
                yield getattr(chunk, "content", str(chunk))
        elif result:
            yield str(result)

    async def _handle_utterance(self, audio) -> bytes | None:
        response_started = time.monotonic()
        self._emit(VoiceEvent.VOICE_TRANSCRIBING, {})
        stt_started = time.monotonic()
        try:
            result = await self._stt.transcribe(audio)
        except Exception as exc:
            if self._metrics:
                self._metrics.record_transcription_error()
            self._emit(VoiceEvent.VOICE_ERROR, {"stage": "stt", "error": self._friendly_error(exc)})
            self._emit(VoiceEvent.VOICE_READY, {})
            return None
        self._performance.stt_latencies.append(time.monotonic() - stt_started)
        text = result.text.strip()
        if not text:
            return
        # P2.8 — voice → intent: classify the transcript before execution so
        # the transcribed intent is observable on the VOICE_TRANSCRIBED event
        # and in the voice metrics.
        intent = self._intent_engine.classify(text)
        if self._metrics:
            self._metrics.record_utterance()
            self._metrics.record_transcription(intent.value)
        self._emit(VoiceEvent.VOICE_TRANSCRIBED, {"text": text, "intent": intent.value})
        self._emit(VoiceEvent.VOICE_GENERATING, {})
        response_parts: list[str] = []
        runtime_started = time.monotonic()
        barge_monitor = None
        self._barge_event.clear()
        if self._config.enable_barge_in and self._config.microphone_enabled:
            barge_monitor = asyncio.create_task(self._monitor_barge_in())
        try:
            if self._config.streaming:
                await self._stream_response(text, response_parts, runtime_started)
            else:
                async for chunk in self._runtime_stream(text):
                    response_parts.append(chunk)
            if not self._config.streaming and not self._barge_event.is_set():
                await self._speak_chunk("".join(response_parts))
            if response_parts:
                await self._speaker.drain()
        except Exception as exc:
            self._emit(VoiceEvent.VOICE_ERROR, {"stage": "runtime/tts", "error": self._friendly_error(exc)})
            return None
        finally:
            if barge_monitor:
                barge_monitor.cancel()
                await asyncio.gather(barge_monitor, return_exceptions=True)
        if self._barge_event.is_set():
            self._performance.interruptions += 1
            self._performance.cancelled_responses += 1
            if self._metrics:
                self._metrics.record_cancelled()
            self._emit(VoiceEvent.LISTENING_AGAIN, {})
            seed = self._barge_seed
            self._barge_event.clear()
            self._barge_seed = None
            return seed
        self._emit(VoiceEvent.VOICE_FINISHED, {})
        self._emit(VoiceEvent.VOICE_READY, {})
        self._performance.total_latencies.append(time.monotonic() - response_started)
        if self._metrics:
            self._metrics.update_latencies(self._performance)

    async def _stream_response(self, text: str, response_parts: list[str], runtime_started: float) -> None:
        """Produce runtime chunks while a separate consumer feeds Piper."""
        queue = SpeechChunkQueue(maxsize=self._config.queue_limit)
        self._speech_queue = queue
        builder = SpeechChunkBuilder(limit=self._config.stream_chunk_size)
        consumer = asyncio.create_task(self._consume_speech_queue(queue, runtime_started))
        self._speech_consumer = consumer
        first_token = True
        self._emit(VoiceEvent.STREAM_BUFFERING, {})
        try:
            async for chunk in self._runtime_stream(text):
                if first_token:
                    self._performance.runtime_latencies.append(time.monotonic() - runtime_started)
                    first_token = False
                response_parts.append(chunk)
                sentences = builder.feed(chunk) if self._config.stream_sentence_detection else [chunk]
                for sentence in sentences:
                    self._performance.chunk_sizes.append(len(sentence))
                    await queue.put(sentence)
            remainder = builder.flush()
            if remainder:
                self._performance.chunk_sizes.append(len(remainder))
                await queue.put(remainder)
            await queue.close()
            await consumer
            stats = queue.statistics
            if stats.peak_depth:
                self._performance.queue_utilization.append(stats.peak_depth / max(1, self._config.queue_limit))
            self._emit(VoiceEvent.STREAM_COMPLETE, {"chunks": stats.dequeued})
        except asyncio.CancelledError:
            await queue.cancel()
            consumer.cancel()
            raise
        except Exception:
            await queue.cancel()
            consumer.cancel()
            if not self._barge_event.is_set():
                raise
        finally:
            if self._speech_queue is queue:
                self._speech_queue = None
            if self._speech_consumer is consumer:
                self._speech_consumer = None

    async def _consume_speech_queue(self, queue: SpeechChunkQueue, response_started: float) -> None:
        first_audio = True
        while True:
            chunk = await queue.get()
            if chunk is None:
                return
            self._emit(VoiceEvent.STREAM_SPEAKING, {"text": chunk})
            tts_started = time.monotonic()
            await self._speak_chunk(chunk)
            self._performance.tts_latencies.append(time.monotonic() - tts_started)
            if first_audio:
                self._performance.first_word_latencies.append(time.monotonic() - response_started)
                first_audio = False

    async def _monitor_barge_in(self) -> None:
        """Read microphone frames while speech is active and interrupt on energy."""
        started = time.monotonic()
        while self._running and not self._barge_event.is_set():
            try:
                chunk = await asyncio.wait_for(self._mic.read_chunk(), self._config.microphone_timeout)
            except (asyncio.TimeoutError, Exception):
                continue
            if time.monotonic() - self._last_barge_at < self._config.barge_in_cooldown:
                continue
            if self._chunk_has_speech(chunk):
                self._last_barge_at = time.monotonic()
                self._barge_seed = chunk
                self._barge_event.set()
                if self._metrics:
                    self._metrics.record_interruption()
                self._emit(VoiceEvent.BARGE_IN, {"latency": time.monotonic() - started})
                self._emit(VoiceEvent.INTERRUPTING, {})
                await self.stop_current_speech()
                return

    def _chunk_has_speech(self, chunk: bytes) -> bool:
        if not chunk:
            return False
        count = len(chunk) // 2
        if not count:
            return False
        samples = struct.unpack(f"<{count}h", chunk[: count * 2])
        return math.sqrt(sum(sample * sample for sample in samples) / count) >= self._config.barge_in_threshold

    async def stop_current_speech(self) -> None:
        """Stop TTS and discard all queued output without touching Runtime."""
        if self._speech_queue:
            await self._speech_queue.cancel()
        try:
            fade_out = getattr(self._speaker, "fade_out", None)
            if self._config.audio_ducking and callable(fade_out):
                await fade_out(self._config.fade_out_ms)
            await self._tts.stop()
        finally:
            await self._speaker.stop()

    def diagnostics(self) -> WakeDiagnostics:
        """Return a snapshot of wake-word metrics without exposing the engine."""
        return WakeDiagnostics(**self._wake_diagnostics.__dict__)

    def performance_report(self) -> VoicePerformanceReport:
        return self._performance.snapshot()

    async def _speak_chunk(self, text: str) -> None:
        spoken_text = self._formatter.format(text, SpeechEmotion.NEUTRAL)
        if not spoken_text:
            return
        stats = self._formatter.stats
        self._performance.markdown_cleaned = stats.markdown_cleaned
        self._performance.urls_skipped = stats.urls_skipped
        self._performance.code_blocks_skipped = stats.code_blocks_skipped
        self._performance.tables_summarized = stats.tables_summarized
        self._performance.speech_lengths.append(len(spoken_text.split()))
        self._emit(VoiceEvent.VOICE_SPEAKING, {"text": spoken_text})
        if self._config.streaming:
            async for audio in self._tts.stream(spoken_text):
                await self._speaker.write(audio)
        else:
            await self._speaker.write(await self._tts.speak(spoken_text))

    async def push_to_talk_start(self) -> None:
        if not self._config.enable_push_to_talk:
            return
        try:
            await self._mic.start_recording()
        except AttributeError:
            await self._mic.open(self._config.sample_rate, self._config.input_device)
        self._emit(VoiceEvent.VOICE_LISTENING, {"mode": "push_to_talk"})

    async def push_to_talk_stop(self, audio=None) -> None:
        if audio is None:
            audio = await self._mic.stop_recording()
        await self._handle_utterance(audio)

    async def _poll_push_to_talk(self) -> None:
        """Windows-first F9 edge detector kept off the UI thread."""
        if __import__("sys").platform != "win32":
            return
        import ctypes

        get_key_state = ctypes.windll.user32.GetAsyncKeyState
        pressed = False
        while self._running:
            is_down = bool(get_key_state(0x78) & 0x8000)  # VK_F9
            if is_down and not pressed:
                await self.push_to_talk_start()
            elif pressed and not is_down:
                await self.push_to_talk_stop()
            pressed = is_down
            await asyncio.sleep(0.03)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc).lower()
        if "microphone" in message or "input" in message:
            return "Microphone unavailable"
        if "speaker" in message or "output" in message:
            return "Speaker unavailable"
        if "whisper" in message:
            return "Whisper model missing"
        if "piper" in message:
            return "Piper not installed"
        return "Voice engine unavailable"

    def _emit(self, event: VoiceEvent, data: dict) -> None:
        if self._metrics:
            self._metrics.record_event(event.value)
        if self._on_event:
            try:
                self._on_event(event, data)
            except Exception:
                log.debug("voice event callback failed", exc_info=True)
