from __future__ import annotations

from pydantic import BaseModel

class RecoveryMetricsSnapshot(BaseModel):
    checkpoints_created: int
    checkpoints_restored: int
    recovery_attempts: int
    successful_recoveries: int
    failed_recoveries: int

class RecoveryMetricsCollector:
    """Collects observability data for distributed fault tolerance operations."""
    
    def __init__(self) -> None:
        self.checkpoints_created = 0
        self.checkpoints_restored = 0
        self.recovery_attempts = 0
        self.successful_recoveries = 0
        self.failed_recoveries = 0
        
    def record_checkpoint_created(self) -> None:
        self.checkpoints_created += 1
        
    def record_checkpoint_restored(self) -> None:
        self.checkpoints_restored += 1
        
    def record_recovery_attempt(self) -> None:
        self.recovery_attempts += 1
        
    def record_successful_recovery(self) -> None:
        self.successful_recoveries += 1
        
    def record_failed_recovery(self) -> None:
        self.failed_recoveries += 1
        
    def get_metrics(self) -> RecoveryMetricsSnapshot:
        return RecoveryMetricsSnapshot(
            checkpoints_created=self.checkpoints_created,
            checkpoints_restored=self.checkpoints_restored,
            recovery_attempts=self.recovery_attempts,
            successful_recoveries=self.successful_recoveries,
            failed_recoveries=self.failed_recoveries,
        )
