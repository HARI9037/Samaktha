"""Local voice configuration."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class VoiceConfig:
    """Configuration shared by the local voice adapters."""

    microphone_enabled: bool = False
    speaker_enabled: bool = False
    wake_word_enabled: bool = False
    streaming_enabled: bool = True

    # Opt-in keeps existing headless/CI launches hardware-free.
    enable_local_voice: bool = False
    enable_push_to_talk: bool = True
    enable_streaming: bool = True
    wake_enabled: bool = False
    always_listen: bool = False
    wake_word_phrase: str = "Samaktha"
    wake_threshold: float = 0.5
    cooldown_seconds: float = 2.0
    microphone_timeout: float = 2.0
    stream_chunk_size: int = 180
    stream_buffer_ms: int = 250
    stream_sentence_detection: bool = True
    prefetch_chunks: int = 2
    queue_limit: int = 16
    latency_logging: bool = False
    enable_barge_in: bool = True
    barge_in_threshold: int = 650
    barge_in_cooldown: float = 0.75
    audio_ducking: bool = True
    fade_out_ms: int = 150
    speech_rate: float = 1.0
    speech_pitch: float = 1.0
    personality_profile: str = "core"
    expand_numbers: bool = True
    expand_abbreviations: bool = True
    read_code: bool = False
    read_urls: bool = False
    read_tables: bool = False
    read_lists: bool = True

    input_device: Optional[str | int] = None
    output_device: Optional[str | int] = None
    whisper_model: str = "base"
    language: str = "en-US"
    sample_rate: int = 16000
    channels: int = 1
    voice_name: str = "default"

    @property
    def streaming(self) -> bool:
        return self.enable_streaming and self.streaming_enabled

    @property
    def wake_active(self) -> bool:
        return self.wake_enabled or self.wake_word_enabled
