from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED_DUPLICATE = "rejected_duplicate"
    SKIPPED = "skipped"


@dataclass
class Job:
    """Unit of work passed from Bot → queue → workers."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "download"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    max_attempts: int = 3
    retry_on_failure: bool = True


@dataclass
class TaskResult:
    job_id: str
    status: JobStatus
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
