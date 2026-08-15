"""VoiceSession — coordinator for voice lifecycle.

Builds ProductionAgentRuntime, VoiceManager, and connects RuntimeAdapter.
Owns voice lifecycle: start, stop, shutdown, toggle, process_voice.
Handles approval flow via ProductionAgentRuntime.resume().
Does not contain CAP, GAMBIT, Runtime, Provider, Tool, Memory, or Internet logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from app.voice.config import VoiceConfig
from app.voice.voice_manager import VoiceManager
from app.voice.runtime_adapter import VoiceRuntimeAdapter
from app.voice.events import VoiceEvent
from app.voice.metrics import VoiceMetricsCollector
from app.agent.production import ProductionAgentRuntime
from app.agent.models import AgentEvent
from app.core.contracts.pause import ExecutionPause
from app.personality.intent_engine import IntentEngine

log = logging.getLogger(__name__)

_APPROVAL_ACCEPT = frozenset({"yes", "approve", "continue", "ok", "y", "allow"})
_APPROVAL_REJECT = frozenset({"no", "deny", "cancel", "n"})


class VoiceSession:
    """Coordinates the voice subsystem with the production runtime."""

    def __init__(
        self,
        config: VoiceConfig,
        runtime: ProductionAgentRuntime,
        session_id: str = "default",
        on_voice_event: Optional[Callable[[VoiceEvent, dict], None]] = None,
        telemetry: Optional[Any] = None,
        metrics: Optional[VoiceMetricsCollector] = None,
    ) -> None:
        self._config = config
        self._runtime = runtime
        self._session_id = session_id
        self._on_voice_event = on_voice_event
        # P2.8 — voice execution observability: a per-session collector that is
        # registered into the shared telemetry registry on start() so /metrics
        # surfaces real voice activity.
        self._telemetry = telemetry
        self._metrics = metrics or VoiceMetricsCollector()

        self._adapter = VoiceRuntimeAdapter(runtime, session_id)
        self._voice_manager: Optional[VoiceManager] = None
        self._process_task: Optional[asyncio.Task] = None
        self._running = False

        # Approval flow state
        self._pending_pause: Optional[ExecutionPause] = None
        self._pending_task_id: Optional[str] = None
        self._approval_event: asyncio.Event | None = None
        self._approval_result: str | None = None
        self._approval_timeout: float = 30.0

        # P2.8 — voice → intent: deterministic transcript classifier used both
        # to surface intents and to drive spoken CAP approvals.
        self._intent_engine = IntentEngine()
        self._wire_approval()

    @classmethod
    def from_config(
        cls,
        config: VoiceConfig,
        session_id: str = "default",
        on_voice_event: Optional[Callable[[VoiceEvent, dict], None]] = None,
        telemetry: Optional[Any] = None,
        metrics: Optional[VoiceMetricsCollector] = None,
    ) -> "VoiceSession":
        """Create VoiceSession with a new ProductionAgentRuntime."""
        runtime = ProductionAgentRuntime()
        return cls(config, runtime, session_id, on_voice_event, telemetry, metrics)

    def _wire_approval(self) -> None:
        """P2.8 — voice → CAP: route runtime pause events into the voice loop.

        The orchestrator emits ``pause_requested``; ProductionAgentRuntime
        forwards it to its ``_event_callback``. This session wraps that
        callback so CAP approval pauses are announced and resolved by voice.
        """
        if not hasattr(self._runtime, "_event_callback"):
            return
        existing = self._runtime._event_callback

        def _callback(event: Any, data: dict) -> None:
            try:
                if event == AgentEvent.PAUSE_REQUESTED or (
                    hasattr(event, "value")
                    and event.value == AgentEvent.PAUSE_REQUESTED.value
                ):
                    task_id = (data or {}).get("task_id")
                    pause_data = (data or {}).get("pause", {})
                    if task_id and pause_data:
                        asyncio.create_task(self._handle_approval(pause_data, task_id))
            except Exception:
                log.debug("approval wiring failed", exc_info=True)
            if existing:
                try:
                    existing(event, data)
                except Exception:
                    log.debug("runtime event callback failed", exc_info=True)

        self._runtime._event_callback = _callback

    async def _handle_approval(self, pause_data: dict, task_id: str) -> None:
        """Drive one CAP approval pause through the voice approval loop."""
        self._metrics.record_approval_request()
        metadata = pause_data.get("metadata", {})
        pause = ExecutionPause(
            reason=pause_data.get("reason") or "This action requires approval",
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        decision = await self.handle_approval_pause(pause, task_id)
        if decision == "timeout":
            self._metrics.record_approval_timeout()
            # Clear the approval state so a later pause can start fresh.
            self._pending_pause = None
            self._pending_task_id = None
            self._approval_event = None
            self._approval_result = None
            return
        self._metrics.record_approval(decision)
        await self.resume_after_approval(decision)

    async def start(self) -> None:
        """Initialize and start the voice manager."""
        if self._running:
            return

        def voice_event_callback(event: VoiceEvent, data: dict) -> None:
            # P2.8 — a transcribed answer while an approval pause is pending is
            # classified and submitted as the CAP decision.
            if event == VoiceEvent.VOICE_TRANSCRIBED and self.has_pending_approval():
                text = (data or {}).get("text", "")
                if text:
                    asyncio.create_task(self._handle_approval_text(text))
            if self._on_voice_event:
                try:
                    self._on_voice_event(event, data)
                except Exception:
                    log.debug("voice event callback failed", exc_info=True)

        self._voice_manager = VoiceManager(
            config=self._config,
            runtime=self._adapter,
            session_id=self._session_id,
            on_event=voice_event_callback,
            metrics=self._metrics,
        )

        if self._telemetry is not None:
            try:
                self._telemetry.register("voice", self._metrics)
            except Exception:
                log.debug("voice telemetry registration failed", exc_info=True)

        await self._voice_manager.start()
        self._running = True

        if self._config.always_listen or self._config.wake_active:
            self._process_task = asyncio.create_task(self._voice_manager.process_voice())

    async def stop(self) -> None:
        """Stop the voice manager."""
        if not self._running:
            return

        self._running = False

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None

        if self._voice_manager:
            await self._voice_manager.stop()
            self._voice_manager = None

    async def shutdown(self) -> None:
        """Full shutdown of voice session."""
        await self.stop()

    def toggle(self) -> None:
        """Toggle voice listening state."""
        if self._running:
            if self._process_task:
                self._process_task.cancel()
                self._process_task = None
            self._running = False
            if self._voice_manager:
                asyncio.create_task(self._voice_manager.stop())
                self._voice_manager = None
        else:
            asyncio.create_task(self.start())

    async def process_voice(self) -> None:
        """Process voice input loop (for push-to-talk or manual control)."""
        if not self._running or not self._voice_manager:
            return

        if self._config.enable_push_to_talk and not self._config.always_listen and not self._config.wake_active:
            if self._process_task and not self._process_task.done():
                return
            self._process_task = asyncio.create_task(self._voice_manager.process_voice())

    async def push_to_talk_start(self) -> None:
        """Start push-to-talk recording."""
        if self._voice_manager and self._config.enable_push_to_talk:
            await self._voice_manager.push_to_talk_start()

    async def push_to_talk_stop(self) -> None:
        """Stop push-to-talk and process the utterance."""
        if self._voice_manager and self._config.enable_push_to_talk:
            await self._voice_manager.push_to_talk_stop()

    async def submit_text(self, text: str) -> str:
        """P2.8 — run text through the production execution pipeline.

        The single voice → execution entry point: transcribed (or typed) text
        flows through the shared ``VoiceRuntimeAdapter`` →
        ``ProductionAgentRuntime`` → orchestrator, and the final provider
        response is returned as a string. Voice never bypasses the pipeline.
        """
        parts: list[str] = []
        async for chunk in self._adapter.stream_response(text):
            parts.append(chunk)
        return "".join(parts)

    async def _handle_approval_text(self, text: str) -> None:
        """Classify a transcribed answer and submit the CAP decision.

        Matches the whole transcript first, then the leading word, so natural
        answers like "yes please" and "no thanks" are recognized too.
        """
        normalized = text.strip().lower()
        if not normalized:
            return
        words = normalized.split()
        if normalized in _APPROVAL_ACCEPT or words[0] in _APPROVAL_ACCEPT:
            await self.submit_approval("yes")
        elif normalized in _APPROVAL_REJECT or words[0] in _APPROVAL_REJECT:
            await self.submit_approval("no")

    async def handle_approval_pause(
        self,
        pause: ExecutionPause,
        task_id: str,
    ) -> str:
        """Handle a CAP approval pause via voice.

        Announces the pause, listens for approval/denial,
        and returns the decision.
        """
        self._pending_pause = pause
        self._pending_task_id = task_id
        self._approval_event = asyncio.Event()
        self._approval_result = None

        reason = pause.reason or "This action requires approval"
        await self._speak_approval_request(reason)

        try:
            await asyncio.wait_for(self._approval_event.wait(), timeout=self._approval_timeout)
        except asyncio.TimeoutError:
            self._approval_result = "timeout"
            await self._speak_approval_timeout()
            return "timeout"

        return self._approval_result or "deny"

    async def _speak(self, text: str) -> None:
        """Speak text through the voice manager's TTS pipeline, if available."""
        if not (self._voice_manager and self._voice_manager._speaker):
            return
        try:
            from app.voice.speech_formatter import SpeechFormatter, SpeechEmotion
            from app.voice.personality import PersonalityEngine

            personality = PersonalityEngine(self._config.personality_profile)
            formatter = SpeechFormatter(profile=personality)
            spoken = formatter.format(text, SpeechEmotion.NEUTRAL)
            if not spoken or not self._config.speaker_enabled:
                return
            if self._config.streaming:
                async for audio in self._voice_manager._tts.stream(spoken):
                    await self._voice_manager._speaker.write(audio)
            else:
                await self._voice_manager._speaker.write(
                    await self._voice_manager._tts.speak(spoken)
                )
        except Exception:
            log.debug("Voice speech failed", exc_info=True)

    async def _speak_approval_request(self, reason: str) -> None:
        """Speak the approval request to the user."""
        await self._speak(f"Samaktha needs approval to proceed. {reason}. Say approve or deny.")

    async def _speak_approval_timeout(self) -> None:
        """Speak the approval timeout message."""
        await self._speak("Approval timed out. Action cancelled.")

    async def submit_approval(self, decision: str) -> None:
        """Submit an approval decision from voice input."""
        decision = decision.strip().lower()
        valid_accept = {"yes", "approve", "continue", "ok", "y"}
        valid_reject = {"no", "deny", "cancel", "n"}

        if decision in valid_accept:
            self._approval_result = "allow"
        elif decision in valid_reject:
            self._approval_result = "deny"
        else:
            self._approval_result = "ambiguous"
            await self._speak_ambiguous_response()
            return

        if self._approval_event:
            self._approval_event.set()

    async def _speak_ambiguous_response(self) -> None:
        """Speak when the user's answer is ambiguous."""
        await self._speak("I did not understand. Please say approve or deny.")

    async def resume_after_approval(
        self,
        decision: str,
        updates: Optional[dict] = None,
    ) -> Any:
        """Resume a paused pipeline after voice approval."""
        if not self._pending_task_id or not self._pending_pause:
            return None

        if updates is None:
            updates = {}

        permit_decision = "allow" if decision in {"allow", "yes", "approve", "continue", "ok", "y"} else "deny"
        updates["permit"] = {"decision": permit_decision, "reasons": [f"Voice approval: {decision}"]}

        try:
            result = await self._runtime.resume(self._session_id, self._pending_task_id, updates)
            return result
        except Exception as exc:
            log.error("Failed to resume pipeline after approval: %s", exc)
            return None
        finally:
            self._pending_pause = None
            self._pending_task_id = None
            self._approval_event = None
            self._approval_result = None

    def has_pending_approval(self) -> bool:
        """Check if there is a pending approval pause."""
        return self._pending_pause is not None and self._approval_event is not None and not self._approval_event.is_set()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def voice_manager(self) -> Optional[VoiceManager]:
        return self._voice_manager

    @property
    def config(self) -> VoiceConfig:
        return self._config

    @property
    def metrics(self) -> VoiceMetricsCollector:
        """P2.8 — the session's voice metrics collector (registered on start)."""
        return self._metrics
