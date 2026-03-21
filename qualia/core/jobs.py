"""Data models para o sistema de jobs assíncronos."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """Status do ciclo de vida de um job."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled)


class JobType(str, Enum):
    """Tipo de job: execução de um plugin ou pipeline."""
    single = "single"
    pipeline = "pipeline"


@dataclass
class JobStep:
    """Etapa de um pipeline job."""
    plugin_id: str
    status: JobStatus = JobStatus.pending
    progress: float | None = None  # reservado para v2
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "status": self.status.value,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class Job:
    """Representa uma execução assíncrona de plugin ou pipeline."""
    id: str
    type: JobType
    status: JobStatus
    plugin_id: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0
    current_step: int = 0
    total_steps: int = 1
    steps: list[JobStep] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    callback_url: str | None = None
    temp_files: list[str] = field(default_factory=list)
    ttl: int = 3600

    @classmethod
    def create_single(
        cls,
        plugin_id: str,
        callback_url: str | None = None,
        temp_files: list[str] | None = None,
        ttl: int = 3600,
    ) -> "Job":
        return cls(
            id=str(uuid.uuid4()),
            type=JobType.single,
            status=JobStatus.pending,
            plugin_id=plugin_id,
            created_at=datetime.now(timezone.utc),
            total_steps=1,
            callback_url=callback_url,
            temp_files=temp_files or [],
            ttl=ttl,
        )

    @classmethod
    def create_pipeline(
        cls,
        plugin_ids: list[str],
        callback_url: str | None = None,
        temp_files: list[str] | None = None,
        ttl: int = 3600,
    ) -> "Job":
        steps = [JobStep(plugin_id=pid) for pid in plugin_ids]
        return cls(
            id=str(uuid.uuid4()),
            type=JobType.pipeline,
            status=JobStatus.pending,
            plugin_id=plugin_ids[0],
            created_at=datetime.now(timezone.utc),
            total_steps=len(plugin_ids),
            steps=steps,
            callback_url=callback_url,
            temp_files=temp_files or [],
            ttl=ttl,
        )

    @property
    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return elapsed > self.ttl

    def update_progress(self) -> None:
        if self.type == JobType.single:
            return
        completed = sum(1 for s in self.steps if s.status == JobStatus.completed)
        self.progress = completed / self.total_steps

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "plugin_id": self.plugin_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "result": self.result,
            "error": self.error,
        }
        if self.type == JobType.pipeline:
            d["steps"] = [s.to_dict() for s in self.steps]
        return d
