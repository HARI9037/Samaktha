"""Local voice configuration."""

import os
from dataclasses import dataclass, field
from typing import Any, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    if val is None:
        return default
    return val


@dataclass
class VoiceConfig:
    """Configuration shared by the local voice adapters.

    Binds to SAMAKTHA_VOICE_* environment variables and application settings.
    """

    microphone_enabled: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_MICROPHONE_ENABLED", False))
    speaker_enabled: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_SPEAKER_ENABLED", False))
    wake_word_enabled: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_WAKE_WORD_ENABLED", False))
    streaming_enabled: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_STREAMING_ENABLED", True))

    enable_local_voice: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_ENABLED", False))
    enable_push_to_talk: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_PUSH_TO_TALK", True))
    enable_streaming: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_STREAMING", True))
    wake_enabled: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_WAKE_ENABLED", False))
    always_listen: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_ALWAYS_LISTEN", False))
    wake_word_phrase: str = field(default_factory=lambda: _env_str("SAMAKTHA_VOICE_WAKE_PHRASE", "Samaktha"))
    wake_threshold: float = field(default_factory=lambda: _env_float("SAMAKTHA_VOICE_WAKE_THRESHOLD", 0.5))
    cooldown_seconds: float = field(default_factory=lambda: _env_float("SAMAKTHA_VOICE_COOLDOWN_SECONDS", 2.0))
    microphone_timeout: float = field(default_factory=lambda: _env_float("SAMAKTHA_VOICE_MICROPHONE_TIMEOUT", 2.0))
    stream_chunk_size: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_STREAM_CHUNK_SIZE", 180))
    stream_buffer_ms: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_STREAM_BUFFER_MS", 250))
    stream_sentence_detection: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_STREAM_SENTENCE_DETECTION", True))
    prefetch_chunks: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_PREFETCH_CHUNKS", 2))
    queue_limit: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_QUEUE_LIMIT", 16))
    latency_logging: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_LATENCY_LOGGING", False))
    enable_barge_in: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_ENABLE_BARGE_IN", True))
    barge_in_threshold: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_BARGE_IN_THRESHOLD", 650))
    barge_in_cooldown: float = field(default_factory=lambda: _env_float("SAMAKTHA_VOICE_BARGE_IN_COOLDOWN", 0.75))
    audio_ducking: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_AUDIO_DUCKING", True))
    fade_out_ms: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_FADE_OUT_MS", 150))
    speech_rate: float = field(default_factory=lambda: _env_float("SAMAKTHA_VOICE_SPEECH_RATE", 1.0))
    speech_pitch: float = field(default_factory=lambda: _env_float("SAMAKTHA_VOICE_SPEECH_PITCH", 1.0))
    personality_profile: str = field(default_factory=lambda: _env_str("SAMAKTHA_VOICE_PERSONALITY_PROFILE", "core"))
    expand_numbers: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_EXPAND_NUMBERS", True))
    expand_abbreviations: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_EXPAND_ABBREVIATIONS", True))
    read_code: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_READ_CODE", False))
    read_urls: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_READ_URLS", False))
    read_tables: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_READ_TABLES", False))
    read_lists: bool = field(default_factory=lambda: _env_bool("SAMAKTHA_VOICE_READ_LISTS", True))

    input_device: Optional[str | int] = None
    output_device: Optional[str | int] = None
    whisper_model: str = field(default_factory=lambda: _env_str("SAMAKTHA_VOICE_WHISPER_MODEL", "base"))
    language: str = field(default_factory=lambda: _env_str("SAMAKTHA_VOICE_LANGUAGE", "en-US"))
    sample_rate: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_SAMPLE_RATE", 16000))
    channels: int = field(default_factory=lambda: _env_int("SAMAKTHA_VOICE_CHANNELS", 1))
    voice_name: str = field(default_factory=lambda: _env_str("SAMAKTHA_VOICE_VOICE_NAME", "default"))

    @property
    def streaming(self) -> bool:
        return self.enable_streaming and self.streaming_enabled

    @property
    def wake_active(self) -> bool:
        return self.wake_enabled or self.wake_word_enabled

    @classmethod
    def from_settings(cls, settings: Any) -> "VoiceConfig":
        """Create VoiceConfig from application Settings object."""
        return cls(
            microphone_enabled=getattr(settings, "voice_microphone_enabled", False),
            speaker_enabled=getattr(settings, "voice_speaker_enabled", False),
            wake_word_enabled=getattr(settings, "voice_wake_word_enabled", False),
            streaming_enabled=getattr(settings, "voice_streaming_enabled", True),
            enable_local_voice=getattr(settings, "voice_enabled", False),
            enable_push_to_talk=getattr(settings, "voice_push_to_talk", True),
            enable_streaming=getattr(settings, "voice_streaming", True),
            wake_enabled=getattr(settings, "voice_wake_enabled", False),
            always_listen=getattr(settings, "voice_always_listen", False),
            wake_word_phrase=getattr(settings, "voice_wake_phrase", "Samaktha"),
            wake_threshold=getattr(settings, "voice_wake_threshold", 0.5),
            cooldown_seconds=getattr(settings, "voice_cooldown_seconds", 2.0),
            microphone_timeout=getattr(settings, "voice_microphone_timeout", 2.0),
            stream_chunk_size=getattr(settings, "voice_stream_chunk_size", 180),
            stream_buffer_ms=getattr(settings, "voice_stream_buffer_ms", 250),
            stream_sentence_detection=getattr(settings, "voice_stream_sentence_detection", True),
            prefetch_chunks=getattr(settings, "voice_prefetch_chunks", 2),
            queue_limit=getattr(settings, "voice_queue_limit", 16),
            latency_logging=getattr(settings, "voice_latency_logging", False),
            enable_barge_in=getattr(settings, "voice_enable_barge_in", True),
            barge_in_threshold=getattr(settings, "voice_barge_in_threshold", 650),
            barge_in_cooldown=getattr(settings, "voice_barge_in_cooldown", 0.75),
            audio_ducking=getattr(settings, "voice_audio_ducking", True),
            fade_out_ms=getattr(settings, "voice_fade_out_ms", 150),
            speech_rate=getattr(settings, "voice_speech_rate", 1.0),
            speech_pitch=getattr(settings, "voice_speech_pitch", 1.0),
            personality_profile=getattr(settings, "voice_personality_profile", "core"),
            expand_numbers=getattr(settings, "voice_expand_numbers", True),
            expand_abbreviations=getattr(settings, "voice_expand_abbreviations", True),
            read_code=getattr(settings, "voice_read_code", False),
            read_urls=getattr(settings, "voice_read_urls", False),
            read_tables=getattr(settings, "voice_read_tables", False),
            read_lists=getattr(settings, "voice_read_lists", True),
            input_device=getattr(settings, "voice_input_device", None),
            output_device=getattr(settings, "voice_output_device", None),
            whisper_model=getattr(settings, "voice_whisper_model", "base"),
            language=getattr(settings, "voice_language", "en-US"),
            sample_rate=getattr(settings, "voice_sample_rate", 16000),
            channels=getattr(settings, "voice_channels", 1),
            voice_name=getattr(settings, "voice_voice_name", "default"),
        )
