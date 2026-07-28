"""Low-overhead voice latency reporting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VoicePerformanceReport:
    stt_latencies: list[float] = field(default_factory=list)
    runtime_latencies: list[float] = field(default_factory=list)
    tts_latencies: list[float] = field(default_factory=list)
    first_word_latencies: list[float] = field(default_factory=list)
    total_latencies: list[float] = field(default_factory=list)
    chunk_sizes: list[int] = field(default_factory=list)
    queue_utilization: list[float] = field(default_factory=list)
    interruptions: int = 0
    interruption_latencies: list[float] = field(default_factory=list)
    cancelled_responses: int = 0
    recovery_times: list[float] = field(default_factory=list)
    markdown_cleaned: int = 0
    urls_skipped: int = 0
    code_blocks_skipped: int = 0
    tables_summarized: int = 0
    speech_lengths: list[int] = field(default_factory=list)

    @staticmethod
    def _average(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @property
    def average_stt_latency(self) -> float: return self._average(self.stt_latencies)
    @property
    def average_runtime_latency(self) -> float: return self._average(self.runtime_latencies)
    @property
    def average_tts_latency(self) -> float: return self._average(self.tts_latencies)
    @property
    def average_first_word_latency(self) -> float: return self._average(self.first_word_latencies)
    @property
    def average_total_response(self) -> float: return self._average(self.total_latencies)
    @property
    def average_chunk_size(self) -> float: return self._average([float(x) for x in self.chunk_sizes])
    @property
    def average_queue_utilization(self) -> float: return self._average(self.queue_utilization)
    @property
    def average_interruption_latency(self) -> float: return self._average(self.interruption_latencies)
    @property
    def average_recovery_time(self) -> float: return self._average(self.recovery_times)
    @property
    def average_speech_length(self) -> float: return self._average([float(x) for x in self.speech_lengths])

    def snapshot(self) -> "VoicePerformanceReport":
        return VoicePerformanceReport(
            list(self.stt_latencies), list(self.runtime_latencies),
            list(self.tts_latencies), list(self.first_word_latencies),
            list(self.total_latencies), list(self.chunk_sizes),
            list(self.queue_utilization), self.interruptions,
            list(self.interruption_latencies), self.cancelled_responses,
            list(self.recovery_times),
            self.markdown_cleaned, self.urls_skipped, self.code_blocks_skipped,
            self.tables_summarized, list(self.speech_lengths),
        )
